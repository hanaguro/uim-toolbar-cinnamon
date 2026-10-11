/* See LICENSE. Based on the behaviour of uim's Qt helper toolbar. */
const Applet = imports.ui.applet;
const PopupMenu = imports.ui.popupMenu;
const Main = imports.ui.main;
const Tooltips = imports.ui.tooltips;
const St = imports.gi.St;
const Gio = imports.gi.Gio;
const GLib = imports.gi.GLib;
const Clutter = imports.gi.Clutter;
const Mainloop = imports.mainloop;
const ByteArray = imports.byteArray;

class UimToolbar extends Applet.Applet {
    constructor(metadata, orientation, panelHeight, instanceId) {
        super(orientation, panelHeight, instanceId);
        this._path = metadata.path;
        this._orientation = orientation;
        this._alive = true;
        this._proc = null;
        this._cancel = null;
        this._restartId = 0;
        this._writeQueue = [];
        this._writing = false;
        this._connected = false;
        this._menus = [];
        this._tips = [];
        this._openMenus = new Set();
        this._pendingRender = false;
        this._branches = [];
        this._config = {display: 'always', dark: false, tools: []};
        this._manager = new PopupMenu.PopupMenuManager(this);
        this._contextSignal = this._applet_context_menu.connect('open-state-changed', (menu, open) => {
            if (open) this._openMenus.add(menu);
            else {
                this._openMenus.delete(menu);
                if (this._pendingRender && this._openMenus.size === 0) this._deferRender();
            }
        });
        this._box = new St.BoxLayout({style_class: 'uim-toolbar-box'});
        this.actor.add_child(this._box);
        this.setAllowedLayout(Applet.AllowedLayout.BOTH);
        this.set_applet_tooltip('uim');
        this._loadOptions();
        this._render();
        this._start();
    }

    _loadOptions() {
        this._options = {python: 'python3', iconSize: 16, buttonSize: 26,
            pixmapDirs: ['/usr/share/uim/pixmaps', '/usr/local/share/uim/pixmaps'],
            mock: false, commands: {}};
        try {
            let file = Gio.File.new_for_path(GLib.build_filenamev([this._path, 'options.json']));
            let [ok, data] = file.load_contents(null);
            if (ok) Object.assign(this._options, JSON.parse(ByteArray.toString(data)));
        } catch (e) { global.logError(e); }
        this._options.iconSize = Math.max(8, Math.min(64, Number(this._options.iconSize) || 16));
        this._options.buttonSize = Math.max(this._options.iconSize, Math.min(80, Number(this._options.buttonSize) || 26));
    }

    _start() {
        if (!this._alive || this._proc) return;
        try {
            let argv = [this._options.python, GLib.build_filenamev([this._path, 'uim_bridge.py'])];
            if (this._options.mock) argv.push('--mock');
            let proc = Gio.Subprocess.new(argv,
                Gio.SubprocessFlags.STDIN_PIPE | Gio.SubprocessFlags.STDOUT_PIPE);
            this._proc = proc;
            this._cancel = new Gio.Cancellable();
            this._writeQueue = [];
            this._writing = false;
            let stream = new Gio.DataInputStream({base_stream: proc.get_stdout_pipe()});
            this._read(stream, proc, this._cancel);
            proc.wait_async(null, (p, result) => {
                try { p.wait_finish(result); } catch (e) { global.logError(e); }
                if (this._proc !== proc) return;
                this._cancel.cancel();
                this._proc = null;
                this._connected = false;
                this._branches = [];
                this._writeQueue = [];
                this._renderWhenSafe();
                this._scheduleRestart();
            });
        } catch (e) {
            global.logError(e);
            this._proc = null;
            this._scheduleRestart();
        }
    }

    _scheduleRestart() {
        if (!this._alive || this._restartId) return;
        this._restartId = Mainloop.timeout_add_seconds(3, () => {
            this._restartId = 0;
            this._start();
            return false;
        });
    }

    _read(stream, proc, cancel) {
        stream.read_line_async(GLib.PRIORITY_DEFAULT, cancel, (s, result) => {
            try {
                let [line] = s.read_line_finish_utf8(result);
                if (line === null || !this._alive || this._proc !== proc) return;
                this._receive(JSON.parse(line));
                this._read(stream, proc, cancel);
            } catch (e) {
                if (this._alive && !cancel.is_cancelled()) {
                    global.logError(e);
                    try { proc.force_exit(); } catch (_) {}
                }
            }
        });
    }

    _receive(obj) {
        if (obj.type === 'config') this._config = obj.config;
        else if (obj.type === 'properties') this._branches = obj.branches;
        else if (obj.type === 'status') {
            this._connected = obj.connected;
            if (!obj.connected) this._branches = [];
        } else return;
        this._renderWhenSafe();
    }

    _send(obj) {
        if (!this._proc || !this._alive) return;
        if (this._writeQueue.length >= 64) return;
        this._writeQueue.push(ByteArray.fromString(JSON.stringify(obj) + '\n'));
        this._flush();
    }

    _flush() {
        if (this._writing || !this._proc || !this._writeQueue.length) return;
        this._writing = true;
        let proc = this._proc;
        let cancel = this._cancel;
        let bytes = this._writeQueue.shift();
        proc.get_stdin_pipe().write_all_async(bytes, GLib.PRIORITY_DEFAULT, cancel, (s, result) => {
            try { s.write_all_finish(result); }
            catch (e) {
                if (this._alive && !cancel.is_cancelled()) {
                    global.logError(e);
                    try { proc.force_exit(); } catch (_) {}
                }
            }
            if (this._proc === proc) {
                this._writing = false;
                this._flush();
            }
        });
    }

    _icon(id, themeIcon) {
        if (id && /^[A-Za-z0-9_.-]+$/.test(id)) {
            for (let dir of this._options.pixmapDirs) {
                let names = this._config.dark ? [id + '_dark_background.png', id + '.png'] : [id + '.png'];
                for (let name of names) {
                    let file = Gio.File.new_for_path(GLib.build_filenamev([dir, name]));
                    if (file.query_exists(null))
                        return new St.Icon({gicon: new Gio.FileIcon({file: file}),
                            icon_type: St.IconType.FULLCOLOR, icon_size: this._options.iconSize});
                }
            }
        }
        if (themeIcon)
            return new St.Icon({icon_name: themeIcon, icon_type: St.IconType.SYMBOLIC,
                icon_size: this._options.iconSize});
        return null;
    }

    _button(id, label, tooltip, themeIcon) {
        let button = new St.Button({style_class: 'uim-toolbar-button', reactive: true,
            can_focus: true, track_hover: true,
            style: `min-width: ${this._options.buttonSize}px; min-height: ${this._options.buttonSize}px;`});
        button.set_child(this._icon(id, themeIcon) || new St.Label({text: label || '?'}));
        this._box.add_child(button);
        this._tips.push(new Tooltips.Tooltip(button, tooltip || label || 'uim'));
        return button;
    }

    _renderWhenSafe() {
        if (!this._alive) return;
        if (this._openMenus.size > 0) this._pendingRender = true;
        else this._render();
    }

    _clear() {
        for (let tip of this._tips) tip.destroy();
        this._tips = [];
        for (let menu of this._menus) menu.destroy();
        this._menus = [];
        this._openMenus.clear();
        this._box.destroy_all_children();
    }

    _render() {
        if (!this._alive) return;
        this._pendingRender = false;
        this._clear();
        this._box.vertical = this._orientation === St.Side.LEFT || this._orientation === St.Side.RIGHT;
        let direct = this._branches.some(b => b.icon === 'direct' || b.icon.endsWith('_direct'));
        let visible = this._config.display === 'always' || (this._config.display === 'mode' && !direct);
        if (!this._connected || !this._branches.length || !visible) {
            let text = this._connected ? 'uim' : 'uim: disconnected (retrying)';
            if (this._options.mock) text += ' [mock]';
            let fallback = this._button('uim-icon', '?', text, 'input-keyboard');
            fallback.connect('clicked', () => this._send({type: 'refresh'}));
        } else {
            for (let branch of this._branches) this._addBranch(branch);
            for (let tool of this._config.tools) {
                if (!tool.visible) continue;
                let button = this._button(tool.icon, tool.fallback, tool.label, tool.themeIcon);
                button.connect('clicked', () => this._launch(tool));
            }
        }
        this._rebuildContext();
    }

    _addBranch(branch) {
        let button = this._button(branch.icon, branch.label, branch.tooltip, null);
        let menu = new PopupMenu.PopupMenu(button, this._orientation);
        Main.uiGroup.add_actor(menu.actor);
        menu.actor.hide();
        this._manager.addMenu(menu);
        this._menus.push(menu);
        menu.connect('open-state-changed', (m, open) => {
            if (open) this._openMenus.add(menu);
            else {
                this._openMenus.delete(menu);
                // Do not destroy the menu while its close/activate signals are running.
                if (this._pendingRender && this._openMenus.size === 0)
                    this._deferRender();
            }
        });
        for (let leaf of branch.items) {
            let item = new PopupMenu.PopupMenuItem(leaf.label);
            let icon = this._icon(leaf.icon, null);
            if (icon) item.addActor(icon, {span: 0});
            item.setShowDot(leaf.selected);
            if (leaf.tooltip) this._tips.push(new Tooltips.Tooltip(item.actor, leaf.tooltip));
            item.connect('activate', () => this._send({type: 'activate', command: leaf.command}));
            menu.addMenuItem(item);
        }
        button.connect('clicked', () => menu.toggle());
    }

    _deferRender() {
        if (this._renderIdle) return;
        this._renderIdle = Mainloop.idle_add(() => {
            this._renderIdle = 0;
            this._renderWhenSafe();
            return false;
        });
    }

    _rebuildContext() {
        // Remove only our items: preserve Cinnamon's Configure/Remove actions.
        for (let item of this._contextItems || []) item.destroy();
        this._contextItems = [];
        let actions = this._config.tools.map(tool => [tool.label, () => this._launch(tool)]);
        actions.push(['uim の状態を再取得', () => this._send({type: 'refresh'})]);
        actions.push(['uim 接続を再起動', () => {
            if (this._proc) this._proc.force_exit(); else this._start();
        }]);
        actions.push(['アプレットの options.json を開く', () => {
            try { Gio.AppInfo.launch_default_for_uri(Gio.File.new_for_path(
                GLib.build_filenamev([this._path, 'options.json'])).get_uri(), null); }
            catch (e) { global.logError(e); Main.notifyError('uim', String(e)); }
        }]);
        let index = 0;
        for (let [label, callback] of actions) {
            let item = new PopupMenu.PopupMenuItem(label);
            item.connect('activate', callback);
            this._applet_context_menu.addMenuItem(item, index++);
            this._contextItems.push(item);
        }
    }

    _launch(tool) {
        let override = this._options.commands[tool.id];
        let argv = Array.isArray(override) ? override : [tool.command];
        try {
            if (!argv.length || !argv.every(x => typeof x === 'string')) throw new Error('Invalid command argv');
            GLib.spawn_async(null, argv, null, GLib.SpawnFlags.SEARCH_PATH, null);
        } catch (e) {
            global.logError(e);
            Main.notifyError('uim: 起動できません', argv.join(' ') + '\n' + String(e));
        }
    }

    on_orientation_changed(orientation) {
        this._orientation = orientation;
        if (!this._box) return;
        for (let menu of this._menus) menu.close();
        this._renderWhenSafe();
    }

    on_applet_removed_from_panel() {
        this._alive = false;
        if (this._restartId) Mainloop.source_remove(this._restartId);
        if (this._renderIdle) Mainloop.source_remove(this._renderIdle);
        if (this._cancel) this._cancel.cancel();
        if (this._proc) {
            try { this._proc.force_exit(); } catch (_) {}
            this._proc = null;
        }
        if (this._contextSignal) this._applet_context_menu.disconnect(this._contextSignal);
        this._clear();
    }
}

function main(metadata, orientation, panelHeight, instanceId) {
    return new UimToolbar(metadata, orientation, panelHeight, instanceId);
}
