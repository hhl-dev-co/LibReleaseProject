import customtkinter as ctk
import subprocess
import os
import json
import tkinter as tk
from tkinter import filedialog, messagebox, Menu
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
    print("모니터 정보:", get_monitors())
    print("열린 창 목록:", [w.title for w in gw.getAllWindows() if w.title][:5])
    print("라이브러리 로드 성공!")
except Exception as e:
    print(f"오류 발생: {e}")
    
try:
    from icoextract import IconExtractor
except ImportError:
    IconExtractor = None

CONFIG_FILE = "launcher_config.json"
BAT_FILENAME = "bc4_build_cmd.bat"

class ToolTip:
    def __init__(self, widget):
        self.widget = widget
        self.text = ""
        self.tooltip_window = None
        self.widget.bind("<Enter>", self.show_tooltip, add="+")
        self.widget.bind("<Leave>", self.hide_tooltip, add="+")

    def show_tooltip(self, event=None):
        if self.tooltip_window or not self.text: return
        x = self.widget.winfo_rootx() + (self.widget.winfo_width() // 2) - 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 5
        self.tooltip_window = tk.Toplevel(self.widget)
        self.tooltip_window.wm_overrideredirect(True)
        self.tooltip_window.attributes("-topmost", True)
        self.tooltip_window.wm_geometry(f"+{x}+{y}")
        label = tk.Label(self.tooltip_window, text=self.text, background="#2C3E50", foreground="white", 
                         relief="solid", borderwidth=1, font=("Segoe UI", 11))
        label.pack(ipadx=5, ipady=2)

    def hide_tooltip(self, event=None):
        if self.tooltip_window:
            self.tooltip_window.destroy()
            self.tooltip_window = None

class MiniLauncher(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        self.load_config()
        self.validate_position()
        
        self.title("Dev_Toolbar")
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.wm_attributes("-transparentcolor", "grey")
        self.configure(fg_color="grey")
        
        self.update_idletasks()
        self.geometry(f"+{int(self.last_x)}+{int(self.last_y)}")
        self.update_idletasks()

        self.context_menu = Menu(self, tearoff=0, bg="#2C3E50", fg="white", activebackground="#34495E")

        self.main_frame = ctk.CTkFrame(self, fg_color="#1E272E", corner_radius=6)
        self.main_frame.pack(fill="both", expand=True, padx=1, pady=1)

        self.drag_handle = ctk.CTkLabel(self.main_frame, text=" ⣿ ", text_color="#7F8C8D", cursor="fleur", font=("Arial", 18))
        self.drag_handle.bind("<Button-1>", self.click_window)
        self.drag_handle.bind("<ButtonRelease-1>", self.on_bg_release)
        self.drag_handle.bind("<B1-Motion>", self.drag_window)

        self.folder_label = ctk.CTkLabel(self.main_frame, text="경로 없음", text_color="#F1C40F", font=("Segoe UI", 12, "bold"), cursor="hand2")
        self.folder_label.bind("<Button-3>", self.show_context_menu)

        self.btn_auto = self.add_button("🚀\n\nAuto Build", self.run_build, "#2980B9", width=75, height=55)
        self.btn_clean = self.add_button("🧹\n\nClean Build", self.run_clean, "#8E44AD", width=75, height=55)
        self.btn_log = self.add_button("🗑\n\nLog", self.run_clear_logs, "#D35400", width=75, height=55)
        
        self.custom_buttons = []
        ctrl_size = 40
        self.btn_setting = self.add_button("📁", self.force_set_path, "#7F8C8D", width=ctrl_size, height=ctrl_size, font_size=12)
        self.btn_minimize = self.add_button("➖", self.minimize_to_tray, "#5DADE2", width=ctrl_size, height=ctrl_size, font_size=12) 
        self.btn_close = self.add_button("❌", self.destroy_app, "#C0392B", width=ctrl_size, height=ctrl_size, font_size=12)

        self.action_buttons = [
            {"widget": self.btn_auto, "color": "#2980B9"},
            {"widget": self.btn_clean, "color": "#8E44AD"},
            {"widget": self.btn_log, "color": "#D35400"}
        ]
        self.folder_tooltip = ToolTip(self.folder_label)
        self.update_folder_label()
        self.update_button_states()
        
        self.after(100, lambda: self.geometry(f"+{int(self.last_x)}+{int(self.last_y)}"))
        self.refresh_custom_buttons() 
        
        self._drag_timer = None
        self._is_draggable = False

        self.main_frame.bind("<Button-3>", self.show_context_menu)
        self.main_frame.bind("<Button-1>", self.on_bg_click)
        self.folder_label.bind("<Button-1>", self.on_bg_click)
        self.main_frame.bind("<B1-Motion>", self.drag_window)
        self.folder_label.bind("<B1-Motion>", self.drag_window)
        self.main_frame.bind("<ButtonRelease-1>", self.on_bg_release)
        self.folder_label.bind("<ButtonRelease-1>", self.on_bg_release)

    def add_button(self, text, command, color, side="left", width=100, font_size=11, height=32, image=None):
        btn = ctk.CTkButton(self.main_frame, text=text, fg_color=color, corner_radius=8, width=width, height=height,
                            font=("Segoe UI", font_size, "bold"), anchor="center", cursor="hand2",
                            command=command, image=image)
        btn.pack(side=side, padx=3, pady=8)
        return btn

    def show_context_menu(self, event):
        if "button" in str(event.widget).lower(): return
        self.context_menu.delete(0, "end")
        has_path = bool(self.bat_folder)
        fg_color = "white" if has_path else "#7F8C8D"
        act_bg = "#34495E" if has_path else "#2C3E50" 
        
        cmd_open = self.open_explorer_direct if has_path else lambda: None
        cmd_clear = self.clear_saved_path if has_path else lambda: None
        
        self.context_menu.add_command(label="📁 폴더 바로 열기", command=cmd_open, foreground=fg_color, activebackground=act_bg)
        self.context_menu.add_command(label="🔝 맨 앞으로 보내기", command=self.set_always_on_top)
        self.context_menu.add_command(label="⏬ 맨 뒤로 보내기", command=self.set_send_to_back)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="🔄 가로/세로 전환", command=lambda: self.toggle_orientation(keep_state=False))
        self.context_menu.add_separator()
        self.context_menu.add_command(label="➕ 앱 파일 찾기 추가", command=self.add_external_app)
        self.context_menu.add_command(label="🎯 실행 중인 앱에서 추가", command=self.show_running_apps_selector)
        self.context_menu.add_command(label="⚙️ 외부 프로그램 편집/삭제", command=self.manage_external_apps)
        self.context_menu.add_command(label="🧹 모두 지우기", command=self.clear_external_apps)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="❓ 도움말", command=self.show_help_popup)
        self.context_menu.add_command(label="🧹 설정된 경로 Clear", command=cmd_clear, foreground=fg_color, activebackground=act_bg)
        self.context_menu.post(event.x_root, event.y_root)

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
            except Exception: self.set_default_config()
        else: self.set_default_config()

    def set_default_config(self):
        self.bat_folder = ""; self.custom_apps = []; self.orientation = "vertical"
        self.last_x = 100; self.last_y = 100

    def save_config(self):
        try:
            data = {
                "bat_folder": self.bat_folder, "custom_apps": self.custom_apps,
                "orientation": self.orientation, "last_x": int(self.last_x), "last_y": int(self.last_y)
            }
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
        except Exception as e: print(f"Save failed: {e}")

    def add_external_app(self):
        path = filedialog.askopenfilename(title="실행 파일 선택", filetypes=[("실행 파일", "*.exe"), ("모든 파일", "*.*")])
        if path and path not in self.custom_apps:
            self.custom_apps.append(path); self.save_config(); self.refresh_custom_buttons()

    def show_running_apps_selector(self):
        selector = ctk.CTkToplevel(self)
        selector.title("실행 중인 앱 선택"); selector.geometry("400x500"); selector.attributes("-topmost", True)
        ctk.CTkLabel(selector, text="추가할 프로그램을 선택하세요", font=("Segoe UI", 13, "bold")).pack(pady=10)
        scroll = ctk.CTkScrollableFrame(selector, width=350, height=350); scroll.pack(padx=10, pady=10, fill="both", expand=True)
        seen_paths = set()
        for win in gw.getAllWindows():
            if win.title and win._hWnd:
                try:
                    _, pid = win32process.GetWindowThreadProcessId(win._hWnd)
                    exe_path = psutil.Process(pid).exe()
                    if exe_path not in seen_paths and "Windows" not in exe_path:
                        seen_paths.add(exe_path)
                        ctk.CTkButton(scroll, text=f"{win.title[:30]}...", fg_color="#34495E", 
                                      command=lambda p=exe_path: self.add_captured_app(p, selector)).pack(pady=2, fill="x")
                except: continue

    def add_captured_app(self, path, window):
        if path not in self.custom_apps:
            self.custom_apps.append(path); self.save_config(); self.refresh_custom_buttons()
        window.destroy()

    def manage_external_apps(self):
        win = ctk.CTkToplevel(self); win.title("앱 편집/삭제"); win.geometry("400x450"); win.attributes("-topmost", True)
        scroll = ctk.CTkScrollableFrame(win, width=350, height=350); scroll.pack(padx=10, pady=10, fill="both", expand=True)
        if not self.custom_apps: ctk.CTkLabel(scroll, text="등록된 프로그램이 없습니다.").pack(pady=20); return
        for path in self.custom_apps:
            frame = ctk.CTkFrame(scroll, fg_color="transparent"); frame.pack(fill="x", pady=2)
            ctk.CTkLabel(frame, text=os.path.basename(path), anchor="w", width=220).pack(side="left", padx=5)
            ctk.CTkButton(frame, text="삭제", width=60, fg_color="#C0392B", 
                          command=lambda p=path: self.remove_single_app(p, win)).pack(side="right", padx=5)

    def remove_single_app(self, path, window):
        if path in self.custom_apps:
            self.custom_apps.remove(path); self.save_config(); self.refresh_custom_buttons(); window.destroy(); self.manage_external_apps()

    def clear_external_apps(self):
        if messagebox.askyesno("확인", "등록된 외부 프로그램을 모두 지우시겠습니까?"):
            self.custom_apps = []; self.save_config(); self.refresh_custom_buttons()

    def refresh_custom_buttons(self):
        for btn in self.custom_buttons: btn.destroy()
        self.custom_buttons.clear()
        if not hasattr(self, 'custom_images'): self.custom_images = []
        self.custom_images.clear()
        for app_path in self.custom_apps:
            name = os.path.basename(app_path).replace(".exe", "")
            btn = None
            if IconExtractor and os.path.exists(app_path):
                try:
                    temp_ico = os.path.join(tempfile.gettempdir(), f"{name}_icon.ico")
                    if not os.path.exists(temp_ico): IconExtractor(app_path).export_icon(temp_ico)
                    img = Image.open(temp_ico)
                    icon_img = ctk.CTkImage(light_image=img, dark_image=img, size=(30, 30))
                    self.custom_images.append(icon_img)
                    btn = self.add_button("", lambda p=app_path: os.startfile(p), "#1E272E", width=55, height=55, image=icon_img)
                except: pass
            if btn is None: btn = self.add_button(f"🖥️\n{name[:5]}", lambda p=app_path: os.startfile(p), "#16A085", width=55, height=55)
            ToolTip(btn).text = name
            self.custom_buttons.append(btn)
        self.toggle_orientation(keep_state=True); self.update()

    def toggle_orientation(self, keep_state=False):
        if not keep_state:
            self.orientation = "vertical" if self.orientation == "horizontal" else "horizontal"; self.save_config()
        for widget in self.main_frame.winfo_children(): widget.pack_forget()
        if self.orientation == "horizontal":
            self.drag_handle.pack(side="left", padx=(10, 0))
            self.folder_label.pack(side="left", padx=(5, 10))
            for b in [self.btn_auto, self.btn_clean, self.btn_log] + self.custom_buttons: b.pack(side="left", padx=3, pady=8)
            self.btn_close.pack(side="right", anchor="n", padx=(1, 5), pady=5)
            self.btn_minimize.pack(side="right", anchor="n", padx=1, pady=5)
            self.btn_setting.pack(side="right", anchor="n", padx=(5, 1), pady=5)
        else:
            self.drag_handle.pack(side="top", pady=(10, 0))
            self.folder_label.pack(side="top", pady=(5, 10))
            for b in [self.btn_auto, self.btn_clean, self.btn_log] + self.custom_buttons: b.pack(side="top", padx=10, pady=3)
            self.btn_close.pack(side="bottom", anchor="e", padx=5, pady=(1, 10))
            self.btn_minimize.pack(side="bottom", anchor="e", padx=5, pady=1)
            self.btn_setting.pack(side="bottom", anchor="e", padx=5, pady=(15, 1))
        self.update_idletasks()
        self.geometry(f"+{int(self.last_x)}+{int(self.last_y)}")

    def drag_window(self, event):
        mx, my = int(event.x_root), int(event.y_root)
        if event.widget != self.drag_handle and not getattr(self, '_is_draggable', False): return
        new_x, new_y = mx - self.offset_x, my - self.offset_y
        snap = 30; win_w, win_h = self.winfo_width(), self.winfo_height()
        from screeninfo import get_monitors
        cur_m = None
        for m in get_monitors():
            if m.x <= mx <= m.x + m.width and m.y <= my <= m.y + m.height: cur_m = m; break
        if cur_m:
            if abs(new_x - cur_m.x) < snap: new_x = cur_m.x
            elif abs(new_x + win_w - (cur_m.x + cur_m.width)) < snap: new_x = cur_m.x + cur_m.width - win_w
            if abs(new_y - cur_m.y) < snap: new_y = cur_m.y
            elif abs(new_y + win_h - (cur_m.y + cur_m.height)) < snap: new_y = cur_m.y + cur_m.height - win_h
        self.geometry(f"+{int(new_x)}+{int(new_y)}")

    def click_window(self, event):
        self.offset_x = event.x_root - self.winfo_x(); self.offset_y = event.y_root - self.winfo_y()

    def on_bg_click(self, event):
        self._is_draggable = False; self.click_window(event); self._drag_timer = self.after(300, self.enable_drag)

    def enable_drag(self):
        self._is_draggable = True; self.configure(cursor="fleur")

    def on_bg_release(self, event):
        if self._drag_timer: self.after_cancel(self._drag_timer); self._drag_timer = None
        self.update_idletasks()
        if self.winfo_x() != self.last_x or self.winfo_y() != self.last_y:
            self.last_x, self.last_y = self.winfo_x(), self.winfo_y(); self.save_config()
        self._is_draggable = False; self.configure(cursor="arrow")

    def validate_position(self):
        from screeninfo import get_monitors
        monitors = get_monitors()
        is_visible = any(m.x <= self.last_x <= (m.x + m.width - 50) and m.y <= self.last_y <= (m.y + m.height - 50) for m in monitors)
        if not is_visible: self.last_x = 100; self.last_y = 100

    def reset_position(self, icon=None, item=None):
        self.last_x = 100; self.last_y = 100
        if icon: icon.stop()
        self.after(100, self.restore_and_move)

    def restore_and_move(self):
        self.deiconify(); self.attributes("-topmost", True); self.geometry(f"+100+100"); self.update_idletasks(); self.save_config()

    def execute_cmd(self, arg=""):
        if not self.bat_folder: return
        subprocess.Popen(["cmd.exe", "/c", BAT_FILENAME, "gui_mode", arg], cwd=self.bat_folder, creationflags=subprocess.CREATE_NEW_CONSOLE)

    def run_build(self): self.execute_cmd("build")
    def run_clean(self): self.execute_cmd("clean")
    def run_clear_logs(self): self.execute_cmd("c_log")
    def open_explorer_direct(self):
        if self.bat_folder: os.startfile(self.bat_folder)
    def force_set_path(self):
        path = filedialog.askdirectory(); 
        if path and os.path.exists(os.path.join(path, BAT_FILENAME)): 
            self.bat_folder = path; self.save_config(); self.update_folder_label(); self.update_button_states()
    def minimize_to_tray(self):
        """창을 숨기고 시스템 트레이에 아이콘을 생성합니다."""
        self.withdraw() # 메인 창 숨기기
        
        # 트레이에 표시될 기본 아이콘 생성 (노란색 사각형)
        img = Image.new('RGB', (64, 64), color='#1E272E')
        d = ImageDraw.Draw(img)
        d.rectangle([16, 16, 48, 48], fill='#F1C40F')
        
        # 트레이 메뉴 구성
        menu = pystray.Menu(
            item('열기', self.show_app, default=True),
            item('위치 초기화', self.reset_position),
            item('종료', self.destroy_app)
        )
        
        self.icon = pystray.Icon("DevToolbar", img, "Dev Toolbar", menu)
        
        # 별도 쓰레드에서 트레이 아이콘 실행 (안 그러면 프로그램이 멈춤)
        threading.Thread(target=self.icon.run, daemon=True).start()
    def show_app(self, icon=None, item=None):
        """트레이에서 다시 창을 화면으로 가져옵니다."""
        if icon:
            icon.stop() # 트레이 아이콘 제거
        self.after(100, self.deiconify) # 창 보이기
    def destroy_app(self, icon=None, item=None):
        if icon: icon.stop()
        self.destroy(); os._exit()
        
    def clear_saved_path(self):
        self.bat_folder = ""; self.save_config(); self.update_folder_label(); self.update_button_states()
    def update_folder_label(self):
        name = os.path.basename(self.bat_folder) if self.bat_folder else "경로 없음"
        self.folder_label.configure(text=f"[{name[:10]}]" if self.bat_folder else name)
    def update_button_states(self):
        valid = bool(self.bat_folder and os.path.exists(os.path.join(self.bat_folder, BAT_FILENAME)))
        for b in self.action_buttons: b["widget"].configure(state="normal" if valid else "disabled")
    def set_always_on_top(self): self.attributes("-topmost", True)
    def set_send_to_back(self): self.attributes("-topmost", False); self.attributes("-alpha", 0.5)
    def show_help_popup(self): messagebox.showinfo("도움말", "⚙ 버튼을 통해 경로를 설정하세요.")

if __name__ == "__main__":
    app = MiniLauncher(); app.mainloop()