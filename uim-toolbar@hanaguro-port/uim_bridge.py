#!/usr/bin/env python3
"""uim helper -> JSON-lines bridge. No third-party Python modules required."""
import argparse
import ctypes as C
import ctypes.util
import gettext
import json
import locale
import os
from pathlib import Path
import select
import signal
import sys
import time

TOOLS = [
    ('switcher', 'toolbar-show-switcher-button?', 'Switch input method', 'uim-im-switcher-qt6', 'im_switcher', 'input-keyboard', 'Sw'),
    ('pref', 'toolbar-show-pref-button?', 'Preference', 'uim-pref-qt6', '', 'preferences-system', 'Pref'),
    ('dict', 'toolbar-show-dict-button?', 'Japanese dictionary editor', 'uim-dict-gtk3', 'uim-dict', 'accessories-dictionary', 'Dic'),
    ('pad', 'toolbar-show-input-pad-button?', 'Input pad', 'uim-chardict-qt6', '', 'format-text-bold', 'Pad'),
    ('hand', 'toolbar-show-handwriting-input-pad-button?', 'Handwriting input pad', 'uim-tomoe-gtk', '', 'document-edit', 'Hand'),
    ('help', 'toolbar-show-help-button?', 'Help', 'uim-help', '', 'help-contents', 'Help'),
]
_ = gettext.translation('uim', fallback=True).gettext

def decode_message(raw):
    encoding = 'utf-8'
    lines = raw.split(b'\n')
    if len(lines) > 1 and lines[1].startswith(b'charset='):
        encoding = lines[1].split(b'=', 1)[1].decode('ascii', 'replace').strip()
    try:
        return raw.decode(encoding, 'replace')
    except LookupError:
        raise ValueError('Unknown uim charset: ' + encoding)

def parse_properties(text):
    branches = []
    current = None
    for line in text.splitlines()[1:]:
        # Preserve empty fields: they are positions, not separators to discard.
        f = line.split('\t')
        if f[0] == 'branch' and len(f) >= 3:
            current = {'icon': f[1], 'label': f[2], 'tooltip': f[3] if len(f) > 3 else '', 'items': []}
            branches.append(current)
        elif f[0] == 'leaf' and current is not None and len(f) >= 6:
            if f[1] and f[3] and f[4] and f[5]:
                current['items'].append({'icon': f[1], 'label': _(f[3]), 'tooltip': f[4],
                                         'command': f[5], 'selected': len(f) > 6 and f[6] == '*'})
    return branches

def emit(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=True, separators=(',', ':')) + '\n')
    sys.stdout.flush()

class Uim:
    def __init__(self):
        name = os.environ.get('UIM_LIBRARY') or C.util.find_library('uim')
        if not name:
            raise RuntimeError('libuim not found. Install uim or set UIM_LIBRARY.')
        self.lib = C.CDLL(name, mode=C.RTLD_GLOBAL)
        scm_name = C.util.find_library('uim-scm')
        self.scm = C.CDLL(scm_name, mode=C.RTLD_GLOBAL) if scm_name else self.lib
        self.libc = C.CDLL(None)
        self.libc.free.argtypes = [C.c_void_p]
        self.libc.free.restype = None
        self.bind(self.lib, 'uim_init', [], C.c_int)
        self.bind(self.lib, 'uim_quit', [], None)
        self.bind(self.lib, 'uim_helper_read_proc', [C.c_int], None)
        self.bind(self.lib, 'uim_helper_get_message', [], C.c_void_p)
        self.bind(self.lib, 'uim_helper_send_message', [C.c_int, C.c_char_p], None)
        self.bind(self.lib, 'uim_helper_client_get_prop_list', [], None)
        self.bind(self.lib, 'uim_helper_close_client_fd', [C.c_int], None)
        self.bind(self.lib, 'uim_prop_reload_configs', [], None)
        self.bind(self.scm, 'uim_scm_symbol_value_bool', [C.c_char_p], C.c_int)
        self.bind(self.scm, 'uim_scm_symbol_value', [C.c_char_p], C.c_void_p)
        self.bind(self.scm, 'uim_scm_c_symbol', [C.c_void_p], C.c_void_p)
        self.callback_type = C.CFUNCTYPE(None)
        self.bind(self.lib, 'uim_helper_init_client_fd', [self.callback_type], C.c_int)
        self.callback = self.callback_type(self.disconnected)
        self.fd = -1
        if self.lib.uim_init() != 0:
            raise RuntimeError('uim_init failed')

    @staticmethod
    def bind(lib, name, args, result):
        fn = getattr(lib, name)
        fn.argtypes, fn.restype = args, result

    def disconnected(self):
        self.fd = -1

    def boolean(self, name):
        return bool(self.scm.uim_scm_symbol_value_bool(name.encode('ascii')))

    def symbol(self, name):
        value = self.scm.uim_scm_symbol_value(name.encode('ascii'))
        ptr = self.scm.uim_scm_c_symbol(value)
        if not ptr:
            return ''
        try:
            return C.string_at(ptr).decode('utf-8', 'replace')
        finally:
            self.libc.free(ptr)

    def config(self):
        return {'display': self.symbol('toolbar-display-time'),
                'dark': self.boolean('toolbar-icon-for-dark-background?'),
                'tools': [dict(id=t[0], visible=self.boolean(t[1]), label=_(t[2]), command=t[3],
                               icon=t[4], themeIcon=t[5], fallback=t[6]) for t in TOOLS]}

    def connect(self):
        self.fd = self.lib.uim_helper_init_client_fd(self.callback)
        if self.fd >= 0:
            self.lib.uim_helper_client_get_prop_list()
            return True
        return False

    def messages(self):
        self.lib.uim_helper_read_proc(self.fd)
        while True:
            ptr = self.lib.uim_helper_get_message()
            if not ptr:
                break
            try:
                yield decode_message(C.string_at(ptr))
            finally:
                self.libc.free(ptr)

    def close(self):
        if self.fd >= 0:
            self.lib.uim_helper_close_client_fd(self.fd)
        self.lib.uim_quit()

def run(mock=False):
    locale.setlocale(locale.LC_ALL, "")
    uim = None if mock else Uim()
    running = True
    def stop(signum, frame):
        nonlocal running
        running = False
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    cfg = ({'display': 'always', 'dark': False, 'tools':
            [dict(id=t[0], visible=t[0] == 'pref', label=_(t[2]), command=t[3], icon=t[4],
                  themeIcon=t[5], fallback=t[6]) for t in TOOLS]} if mock else uim.config())
    emit({'type': 'config', 'config': cfg})
    mock_branches = parse_properties('prop_list_update\ncharset=UTF-8\nbranch\tmozc\tMozc\tMozc\nleaf\tmozc\tM\tMozc\tMozc\timsw_mozc\t*\nbranch\thiragana\tあ\t入力モード\nleaf\thiragana\tあ\tひらがな\tひらがな入力\tmode_hiragana\t*\nleaf\tdirect\tA\t直接入力\t直接入力\tmode_direct\n')
    if mock:
        emit({'type': 'status', 'connected': True, 'mock': True})
        emit({'type': 'properties', 'branches': mock_branches})
    stdin_fd = sys.stdin.fileno()
    os.set_blocking(stdin_fd, False)
    buffer = b''
    next_connect = 0.0
    reported = None
    try:
        while running:
            if uim and uim.fd < 0 and time.monotonic() >= next_connect:
                uim.connect()
                next_connect = time.monotonic() + 2.0
            connected = mock or uim.fd >= 0
            if connected != reported:
                emit({'type': 'status', 'connected': connected})
                reported = connected
            watches = [stdin_fd]
            helper_fd = uim.fd if uim else -1
            if helper_fd >= 0:
                watches.append(helper_fd)
            ready, unused_write, unused_error = select.select(watches, [], [], 0.5)
            if helper_fd in ready and uim:
                for message in uim.messages():
                    kind = message.split('\n', 1)[0]
                    if kind == 'prop_list_update':
                        emit({'type': 'properties', 'branches': parse_properties(message)})
                    elif kind == 'custom_reload_notify':
                        uim.lib.uim_prop_reload_configs()
                        emit({'type': 'config', 'config': uim.config()})
                        if uim.fd >= 0:
                            uim.lib.uim_helper_client_get_prop_list()
            if stdin_fd not in ready:
                continue
            chunk = os.read(stdin_fd, 65536)
            if not chunk:
                break
            buffer += chunk
            if len(buffer) > 1024 * 1024:
                raise ValueError('stdin buffer too large')
            while b'\n' in buffer:
                line, buffer = buffer.split(b'\n', 1)
                try:
                    obj = json.loads(line)
                    cmd = obj.get('type')
                    if cmd == 'quit':
                        running = False
                    elif cmd == 'refresh' and uim and uim.fd >= 0:
                        uim.lib.uim_helper_client_get_prop_list()
                    elif cmd == 'activate':
                        action = obj.get('command', '')
                        if not isinstance(action, str) or not action or len(action) > 4096 or any(c in action for c in '\n\r\x00'):
                            raise ValueError('invalid property command')
                        if mock:
                            print('mock activate: ' + action, file=sys.stderr, flush=True)
                            if action in ('mode_direct', 'mode_hiragana'):
                                direct = action == 'mode_direct'
                                mock_branches[1]['icon'] = 'direct' if direct else 'hiragana'
                                mock_branches[1]['label'] = 'A' if direct else 'あ'
                                for item in mock_branches[1]['items']:
                                    item['selected'] = item['command'] == action
                                emit({'type': 'properties', 'branches': mock_branches})
                        elif uim.fd >= 0:
                            uim.lib.uim_helper_send_message(uim.fd, ('prop_activate\n' + action + '\n').encode('utf-8'))
                except (ValueError, TypeError, AttributeError) as exc:
                    print('uim-bridge: rejected input: ' + str(exc), file=sys.stderr, flush=True)
    finally:
        if uim:
            uim.close()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mock', action='store_true', help='UI test without libuim; no input-method changes')
    args = parser.parse_args()
    try:
        run(args.mock)
    except BrokenPipeError:
        pass
    except Exception as exc:
        print('uim-bridge: ' + str(exc), file=sys.stderr, flush=True)
        return 1
    return 0

if __name__ == '__main__':
    sys.exit(main())
