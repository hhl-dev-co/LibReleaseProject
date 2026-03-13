import sys
import tkinter as tk
from tkinter import messagebox

# 1. 실행 중 발생하는 모든 에러를 팝업창으로 잡아내기 위한 설정
def show_fatal_error(e):
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror("실행 오류 발생", f"프로그램 실행 중 오류가 발생했습니다:\n\n{str(e)}")
    root.destroy()

try:
    import customtkinter as ctk
    import subprocess
    import os
    import json
    from tkinter import filedialog, Menu
    import pystray
    from pystray import MenuItem as item
    from PIL import Image, ImageDraw
    import threading
    import tempfile
    import pygetwindow as gw
    import psutil
    import win32process
    from screeninfo import get_monitors

    try:
        from icoextract import IconExtractor
    except ImportError:
        IconExtractor = None

    CONFIG_FILE = "launcher_config.json"
    BAT_FILENAME = "bc4_build_cmd.bat"

    # --- ToolTip 클래스 ---
    class ToolTip:
        def __init__(self, widget):
            self.widget = widget
            self.text = ""
            self.tooltip_window = None
            self.widget.bind("<Enter>", self.show_tooltip, add="+")
            self.widget.bind("<Leave>", self.hide_tooltip, add="+")

        def show_tooltip(self, event=None):
            if self.tooltip_window or not self.text: return
            try:
                x = self.widget.winfo_rootx() + (self.widget.winfo_width() // 2) - 20
                y = self.widget.winfo_rooty() + self.widget.winfo_height() + 5
                self.tooltip_window = tk.Toplevel(self.widget)
                self.tooltip_window.wm_overrideredirect(True)
                self.tooltip_window.attributes("-topmost", True)
                self.tooltip_window.wm_geometry(f"+{x}+{y}")
                label = tk.Label(self.tooltip_window, text=self.text, background="#2C3E50", foreground="white", 
                                relief="solid", borderwidth=1, font=("Segoe UI", 11))
                label.pack(ipadx=5, ipady=2)
            except: pass

        def hide_tooltip(self, event=None):
            if self.tooltip_window:
                self.tooltip_window.destroy()
                self.tooltip_window = None

    class MiniLauncher(ctk.CTk):
        def __init__(self):
            super().__init__()
            
            # 초기화 전 기본값 강제 설정
            self.bat_folder = ""
            self.custom_apps = []
            self.orientation = "vertical"
            self.last_x = 100
            self.last_y = 100
            self.custom_buttons = []
            self.custom_images = []

            self.load_config()
            self.validate_position()
            
            self.title("Dev_Toolbar")
            self.overrideredirect(True)
            self.attributes("-topmost", True)
            self.wm_attributes("-transparentcolor", "grey")
            self.configure(fg_color="grey")
            
            # UI 레이아웃 생성
            self.context_menu = Menu(self, tearoff=0, bg="#2C3E50", fg="white", activebackground="#34495E")
            self.main_frame = ctk.CTkFrame(self, fg_color="#1E272E", corner_radius=6)
            self.main_frame.pack(fill="both", expand=True, padx=1, pady=1)

            # 위젯 생성
            self.drag_handle = ctk.CTkLabel(self.main_frame, text=" ⣿ ", text_color="#7F8C8D", cursor="fleur", font=("Arial", 18))
            self.folder_label = ctk.CTkLabel(self.main_frame, text="경로 없음", text_color="#F1C40F", font=("Segoe UI", 12, "bold"), cursor="hand2")

            self.btn_auto = self.add_raw_button("🚀\n\nAuto Build", self.run_build, "#2980B9", 75, 55)
            self.btn_clean = self.add_raw_button("🧹\n\nClean Build", self.run_clean, "#8E44AD", 75, 55)
            self.btn_log = self.add_raw_button("🗑\n\nLog", self.run_clear_logs, "#D35400", 75, 55)
            
            self.action_buttons = [
                {"widget": self.btn_auto, "color": "#2980B9"},
                {"widget": self.btn_clean, "color": "#8E44AD"},
                {"widget": self.btn_log, "color": "#D35400"}
            ]
            
            ctrl_size = 40
            self.btn_setting = self.add_raw_button("📁", self.force_set_path, "#7F8C8D", ctrl_size, ctrl_size, 12)
            self.btn_minimize = self.add_raw_button("➖", self.minimize_to_tray, "#5DADE2", ctrl_size, ctrl_size, 12) 
            self.btn_close = self.add_raw_button("❌", self.destroy_app, "#C0392B", ctrl_size, ctrl_size, 12)

            # 초기 업데이트
            self.folder_tooltip = ToolTip(self.folder_label)
            self.update_folder_label()
            self.update_button_states()
            self.refresh_custom_buttons()
            
            # 이벤트 바인딩
            self.setup_event_bindings()
            
            # 위치 설정
            self.update_idletasks()
            self.geometry(f"+{int(self.last_x)}+{int(self.last_y)}")
            self.after(200, lambda: self.geometry(f"+{int(self.last_x)}+{int(self.last_y)}"))

        def add_raw_button(self, text, command, color, width, height, font_size=11, image=None):
            return ctk.CTkButton(self.main_frame, text=text, fg_color=color, corner_radius=8, 
                                width=width, height=height, font=("Segoe UI", font_size, "bold"),
                                command=command, image=image, cursor="hand2")

        def setup_event_bindings(self):
            self.drag_handle.bind("<Button-1>", self.click_window)
            self.drag_handle.bind("<B1-Motion>", self.drag_window)
            self.drag_handle.bind("<ButtonRelease-1>", self.on_bg_release)
            self.main_frame.bind("<Button-3>", self.show_context_menu)
            self.main_frame.bind("<Button-1>", self.on_bg_click)
            self.folder_label.bind("<Button-1>", self.on_bg_click)
            self.main_frame.bind("<B1-Motion>", self.drag_window)
            self.folder_label.bind("<B1-Motion>", self.drag_window)
            self.main_frame.bind("<ButtonRelease-1>", self.on_bg_release)
            self.folder_label.bind("<ButtonRelease-1>", self.on_bg_release)
            self.folder_label.bind("<Button-3>", self.show_context_menu)

        def load_config(self):
            if os.path.exists(CONFIG_FILE):
                try:
                    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        self.bat_folder = data.get("bat_folder", "")
                        self.custom_apps = data.get("custom_apps", [])
                        self.orientation = data.get("orientation", "vertical")
                        self.last_x = data.get("last_x", 100)
                        self.last_y = data.get("last_y", 100)
                except: pass

        def save_config(self):
            try:
                data = {"bat_folder": self.bat_folder, "custom_apps": self.custom_apps,
                        "orientation": self.orientation, "last_x": int(self.last_x), "last_y": int(self.last_y)}
                with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=4)
            except: pass

        def validate_position(self):
            try:
                monitors = get_monitors()
                is_visible = any(m.x <= self.last_x <= (m.x + m.width - 50) and m.y <= self.last_y <= (m.y + m.height - 50) for m in monitors)
                if not is_visible:
                    self.last_x, self.last_y = 100, 100
            except:
                self.last_x, self.last_y = 100, 100

        def toggle_orientation(self, keep_state=False):
            if not keep_state:
                self.orientation = "vertical" if self.orientation == "horizontal" else "horizontal"
                self.save_config()
            
            for widget in self.main_frame.winfo_children():
                widget.pack_forget()

            if self.orientation == "horizontal":
                self.drag_handle.pack(side="left", padx=(10, 0))
                self.folder_label.pack(side="left", padx=(5, 10))
                for b in [self.btn_auto, self.btn_clean, self.btn_log] + self.custom_buttons:
                    b.pack(side="left", padx=3, pady=8)
                self.btn_close.pack(side="right", padx=(1, 5), pady=5)
                self.btn_minimize.pack(side="right", padx=1, pady=5)
                self.btn_setting.pack(side="right", padx=(5, 1), pady=5)
            else:
                self.drag_handle.pack(side="top", pady=(10, 0))
                self.folder_label.pack(side="top", pady=(5, 10))
                for b in [self.btn_auto, self.btn_clean, self.btn_log] + self.custom_buttons:
                    b.pack(side="top", padx=10, pady=3)
                self.btn_close.pack(side="bottom", padx=5, pady=(1, 10))
                self.btn_minimize.pack(side="bottom", padx=5, pady=1)
                self.btn_setting.pack(side="bottom", padx=5, pady=(15, 1))
            self.update_idletasks()

        def drag_window(self, event):
            if event.widget != self.drag_handle and not getattr(self, '_is_draggable', False): return
            self.attributes("-alpha", 0.7)
            mx, my = int(event.x_root), int(event.y_root)
            nx, ny = mx - self.offset_x, my - self.offset_y
            snap = 30
            ww, wh = self.winfo_width(), self.winfo_height()
            try:
                for m in get_monitors():
                    if m.x <= mx <= m.x + m.width and m.y <= my <= m.y + m.height:
                        if abs(nx - m.x) < snap: nx = m.x
                        elif abs(nx + ww - (m.x + m.width)) < snap: nx = m.x + m.width - ww
                        if abs(ny - m.y) < snap: ny = m.y
                        elif abs(ny + wh - (m.y + m.height)) < snap: ny = m.y + m.height - wh
                        break
            except: pass
            self.geometry(f"+{int(nx)}+{int(ny)}")

        def on_bg_release(self, event):
            if hasattr(self, '_drag_timer') and self._drag_timer: self.after_cancel(self._drag_timer)
            self.attributes("-alpha", 1.0)
            self.update_idletasks()
            self.last_x, self.last_y = self.winfo_x(), self.winfo_y()
            self.save_config()
            self._is_draggable = False
            self.configure(cursor="arrow")

        def click_window(self, event):
            self.offset_x, self.offset_y = event.x_root - self.winfo_x(), event.y_root - self.winfo_y()

        def on_bg_click(self, event):
            self.click_window(event)
            self._drag_timer = self.after(300, lambda: self.set_draggable(True))

        def set_draggable(self, val):
            self._is_draggable = val
            if val: self.configure(cursor="fleur")

        def update_folder_label(self):
            full_name = os.path.basename(os.path.normpath(self.bat_folder)) if self.bat_folder else "경로 없음"
            display_name = full_name[:10] + "..." if len(full_name) > 10 else full_name
            self.folder_label.configure(text=f"[{display_name}]" if self.bat_folder else display_name)
            if hasattr(self, "folder_tooltip"): self.folder_tooltip.text = full_name

        def refresh_custom_buttons(self):
            for b in self.custom_buttons: b.destroy()
            self.custom_buttons.clear()
            for p in self.custom_apps:
                name = os.path.basename(p).replace(".exe", "")
                btn = self.add_raw_button(f"🖥️\n{name[:5]}", lambda p=p: os.startfile(p), "#16A085", 55, 55)
                self.custom_buttons.append(btn)
            self.toggle_orientation(keep_state=True)

        def show_context_menu(self, event):
            self.context_menu.delete(0, "end")
            has_path = bool(self.bat_folder)
            self.context_menu.add_command(label="📁 폴더 바로 열기", command=lambda: os.startfile(self.bat_folder) if has_path else None, state="normal" if has_path else "disabled")
            self.context_menu.add_command(label="➕ 앱 추가", command=self.add_external_app)
            self.context_menu.add_command(label="🎯 실행 앱 추가", command=self.show_running_apps_selector)
            self.context_menu.add_command(label="⚙️ 앱 편집/삭제", command=self.manage_external_apps)
            self.context_menu.add_separator()
            self.context_menu.add_command(label="🔄 가로/세로 전환", command=lambda: self.toggle_orientation(False))
            self.context_menu.add_command(label="❓ 도움말", command=self.show_help_custom)
            self.context_menu.add_separator()
            self.context_menu.add_command(label="❌ 종료", command=self.destroy_app)
            self.context_menu.post(event.x_root, event.y_root)

        def add_external_app(self):
            p = filedialog.askopenfilename(filetypes=[("Exe", "*.exe")])
            if p: self.custom_apps.append(p); self.save_config(); self.refresh_custom_buttons()

        def show_running_apps_selector(self):
            win = ctk.CTkToplevel(self); win.attributes("-topmost", True); win.title("앱 선택")
            scroll = ctk.CTkScrollableFrame(win); scroll.pack(fill="both", expand=True)
            seen = set()
            for w in gw.getAllWindows():
                if w.title:
                    try:
                        _, pid = win32process.GetWindowThreadProcessId(w._hWnd)
                        path = psutil.Process(pid).exe()
                        if path not in seen and "Windows" not in path:
                            seen.add(path)
                            ctk.CTkButton(scroll, text=w.title[:20], command=lambda p=path: self.add_captured_app(p, win)).pack(pady=2)
                    except: continue

        def add_captured_app(self, p, win):
            if p not in self.custom_apps: self.custom_apps.append(p); self.save_config(); self.refresh_custom_buttons()
            win.destroy()

        def manage_external_apps(self):
            win = ctk.CTkToplevel(self); win.geometry("300x400"); win.attributes("-topmost", True); win.title("관리")
            scroll = ctk.CTkScrollableFrame(win); scroll.pack(fill="both", expand=True)
            for p in self.custom_apps:
                f = ctk.CTkFrame(scroll); f.pack(fill="x", pady=2)
                ctk.CTkLabel(f, text=os.path.basename(p)[:15]).pack(side="left", padx=5)
                ctk.CTkButton(f, text="X", width=30, command=lambda p=p: self.remove_app(p, win)).pack(side="right")

        def remove_app(self, p, win):
            self.custom_apps.remove(p); self.save_config(); self.refresh_custom_buttons(); win.destroy(); self.manage_external_apps()

        def show_help_custom(self):
            help_win = ctk.CTkToplevel(self); help_win.title("도움말"); help_win.geometry("400x300"); help_win.attributes("-topmost", True)
            textbox = ctk.CTkTextbox(help_win, font=("Consolas", 12))
            textbox.pack(fill="both", expand=True, padx=10, pady=10)
            textbox.insert("0.0", "[ Dev Toolbar 가이드 ]\n\n1. 드래그: 핸들 또는 배경 꾹 눌러 이동\n2. 자석: 화면 끝 자동 흡착\n3. 경로: [...] 생략 표기 지원")
            textbox.configure(state="disabled")

        def update_button_states(self):
            v = bool(self.bat_folder and os.path.exists(os.path.join(self.bat_folder, BAT_FILENAME)))
            for b in self.action_buttons: b["widget"].configure(state="normal" if v else "disabled")

        def minimize_to_tray(self):
            self.withdraw()
            img = Image.new('RGB', (64, 64), color='#1E272E')
            d = ImageDraw.Draw(img); d.rectangle([16, 16, 48, 48], fill='#F1C40F')
            m = pystray.Menu(item('열기', self.show_app, default=True), item('종료', self.destroy_app))
            self.icon = pystray.Icon("DevToolbar", img, "Dev Toolbar", m)
            threading.Thread(target=self.icon.run, daemon=True).start()

        def show_app(self, icon=None, item=None):
            if icon: icon.stop()
            self.after(100, self.deiconify)

        def destroy_app(self, icon=None, item=None):
            if icon: icon.stop()
            self.destroy(); os._exit(0)

        def run_build(self): self.execute_cmd("build")
        def run_clean(self): self.execute_cmd("clean")
        def run_clear_logs(self): self.execute_cmd("c_log")
        def execute_cmd(self, a):
            if self.bat_folder: subprocess.Popen(["cmd.exe", "/c", BAT_FILENAME, "gui_mode", a], cwd=self.bat_folder, creationflags=subprocess.CREATE_NEW_CONSOLE)
        def force_set_path(self):
            p = filedialog.askdirectory()
            if p: self.bat_folder = p; self.save_config(); self.update_folder_label(); self.update_button_states()

    if __name__ == "__main__":
        app = MiniLauncher()
        app.mainloop()

except Exception as fatal_e:
    show_fatal_error(fatal_e)