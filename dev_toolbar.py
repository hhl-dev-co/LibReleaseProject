import customtkinter as ctk
import subprocess
import os
import json
import tkinter as tk
from tkinter import filedialog, messagebox, Menu
import pystray
from pystray import MenuItem as item
from PIL import Image, ImageDraw, ImageFont
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
HELP_FILE = "help_data.json"
BAT_FILENAME = "bc4_build_cmd.bat"

# ToolTip 클래스는 동일하게 유지
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
    def check_instance_role(self):
        import ctypes
        ERROR_ALREADY_EXISTS = 183
        
        # check_main
        handle_main = ctypes.windll.kernel32.CreateMutexW(None, False, "DevToolbar_Main")
        if ctypes.windll.kernel32.GetLastError() != ERROR_ALREADY_EXISTS:
            return "main", handle_main
        else:
            ctypes.windll.kernel32.CloseHandle(handle_main) # [추가] 내 깃발이 아니면 손잡이를 놓아줍니다!
            
        # check_sub1
        handle_sub1 = ctypes.windll.kernel32.CreateMutexW(None, False, "DevToolbar_Sub1")
        if ctypes.windll.kernel32.GetLastError() != ERROR_ALREADY_EXISTS:
            return "sub1", handle_sub1
        else:
            ctypes.windll.kernel32.CloseHandle(handle_sub1) # [추가]
            
        # check_sub2
        handle_sub2 = ctypes.windll.kernel32.CreateMutexW(None, False, "DevToolbar_Sub2")
        if ctypes.windll.kernel32.GetLastError() != ERROR_ALREADY_EXISTS:
            return "sub2", handle_sub2
        else:
            ctypes.windll.kernel32.CloseHandle(handle_sub2) # [추가]
            
        # already 3 on...
        return "none", None

    def __init__(self):
        super().__init__()

        self.role, self.mutex_handle = self.check_instance_role()
        if self.role == "none":
            messagebox.showerror("실행 제한", "최대 3개의 툴바(Main 1개, Sub 2개)만 실행할 수 있습니다.")
            os._exit(0)
        
        global CONFIG_FILE
        CONFIG_FILE = f"launcher_config_{self.role}.json"

        self.cached_monitors = get_monitors()
        self.load_config()
        self.validate_position()
        
        self.title(f"Dev_Toolbar - {self.role.upper()}") # 타이틀에 역할 표시
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.wm_attributes("-transparentcolor", "grey")
        self.configure(fg_color="grey")
        
        self.update_idletasks()
        self.geometry(f"+{int(self.last_x)}+{int(self.last_y)}")

        self.context_menu = Menu(self, tearoff=0, bg="#2C3E50", fg="white", activebackground="#34495E")
        if self.role == "main":
            frame_bg = "#1E272E" # 메인: 아주 어두운 블루그레이 (기존)
        elif self.role == "sub1":
            frame_bg = "#18324D" # Sub1: 살짝 밝아진 블루그레이
        else:
            frame_bg = "#0E4072" # Sub2: 한 톤 더 밝아진 그레이시 블루
        self.main_frame = ctk.CTkFrame(self, fg_color=frame_bg, corner_radius=6)
        self.main_frame.pack(fill="both", expand=True, padx=1, pady=1)

        # 위젯 생성 2980B9
        # 공통 버튼 생성 (드래그, 폴더, 빌드 3종, 닫기)
        self.drag_handle = ctk.CTkLabel(self.main_frame, text=" ⣿ ", text_color="#7F8C8D", cursor="fleur", font=("Arial", 18))
        self.folder_label = ctk.CTkLabel(self.main_frame, text="경로 없음", text_color="#F1C40F", font=("Segoe UI", 12, "bold"), cursor="hand2")

        self.btn_auto = self.add_raw_button("🚀\n\nAuto Build", self.run_build, "#2980B9", 75, 55)
        self.btn_clean = self.add_raw_button("🧹\n\nClean Build", self.run_clean, "#8E44AD", 75, 55)
        self.btn_log = self.add_raw_button("🗑\n\nLog", self.run_clear_logs, "#D35400", 75, 55)
        self.action_buttons = [{"widget": self.btn_auto, "color": "#2980B9"}, {"widget": self.btn_clean, "color": "#8E44AD"}, {"widget": self.btn_log, "color": "#D35400"}]

        ctrl_size = 40
        self.custom_buttons = []
        self.custom_images = []

        self.btn_close = self.add_raw_button("❌", self.destroy_app, "#C0392B", ctrl_size, ctrl_size, 12)
        ToolTip(self.btn_close).text = "프로그램 종료"

        if self.role == "main":
            self.btn_setting = self.add_raw_button("📁", self.force_set_path, "#2980B9", ctrl_size, ctrl_size, 12)
            self.btn_minimize = self.add_raw_button("➖", self.minimize_to_tray, "#5DADE2", ctrl_size, ctrl_size, 12) 
            ToolTip(self.btn_setting).text = "경로 설정"
            ToolTip(self.btn_minimize).text = "트레이로 최소화"
        else:
            self.custom_apps = [] # Sub 툴바는 외부 앱 버튼을 만들지 않음

        self.setup_bindings() 
        self.update_folder_label()
        self.update_button_states()
        self.refresh_custom_buttons() 
        
        self._drag_timer = None
        self._is_draggable = False
        self.after(150, lambda: self.geometry(f"+{int(self.last_x)}+{int(self.last_y)}"))
        self.after(100, self.force_show_on_taskbar)
        
        # toolbar-connection logic
        if self.role == "main":
            import sys
            cmd = [sys.executable] if getattr(sys, 'frozen', False) else [sys.executable, sys.argv[0]]

            if getattr(self, "launch_sub1", False):
                subprocess.Popen(cmd, creationflags=0x08000000)
            if getattr(self, "launch_sub2", False):
                subprocess.Popen(cmd, creationflags=0x08000000)
        else:
            self.check_main_alive()

    def add_raw_button(self, text, command, color, width, height, font_size=11, image=None):
        return ctk.CTkButton(self.main_frame, text=text, fg_color=color, corner_radius=8, 
                             width=width, height=height, font=("Segoe UI", font_size, "bold"),
                             command=command, image=image, cursor="hand2")

    def setup_bindings(self):
        for w in (self.main_frame, self.folder_label):
            w.bind("<Button-1>", self.click_window)
            w.bind("<B1-Motion>", self.drag_window)
            w.bind("<ButtonRelease-1>", self.on_bg_release)
            w.bind("<Button-3>", self.show_context_menu)
            w.bind("<Button-1>", self.on_bg_click, add="+")

        self.drag_handle.bind("<Button-1>", self.click_handle)
        self.drag_handle.bind("<B1-Motion>", self.drag_window)
        self.drag_handle.bind("<ButtonRelease-1>", self.on_bg_release)

    # [기능 추가] 맨 앞으로 가져오기
    def bring_to_front(self):
        self.attributes("-topmost", True)
        self.lift()

    # [기능 추가] 맨 뒤로 보내기
    def send_to_back(self):
        self.attributes("-topmost", False)
        self.lower()

    def update_folder_label(self):
        if self.bat_folder:
            full_name = os.path.basename(os.path.normpath(self.bat_folder))
            display_name = (full_name[:10] + "...") if len(full_name) > 10 else full_name
            self.folder_label.configure(text=f"[{display_name}]", text_color="#ECF0F1")
            ToolTip(self.folder_label).text = full_name
        else:
            self.folder_label.configure(text="경로 없음", text_color="#F1750F")
            ToolTip(self.folder_label).text = ""

    def show_context_menu(self, event):
        self.context_menu.delete(0, "end")
        
        is_valid_path = bool(self.bat_folder and os.path.exists(os.path.join(self.bat_folder, BAT_FILENAME)))
        menu_state = "normal" if is_valid_path else "disabled"

        self.context_menu.add_command(label="📁 폴더 바로 열기", command=lambda: os.startfile(self.bat_folder) if is_valid_path else None, state=menu_state)
        
        # Sub 툴바를 위한 경로 설정 메뉴 추가 (화면상 버튼 대체)
        if self.role != "main":
            self.context_menu.add_command(label="⚙️ 빌드 경로 설정", command=self.force_set_path)
        self.context_menu.add_separator()
        
        # Main 툴바 전용 메뉴
        if self.role == "main":
            self.context_menu.add_command(label="➕ 앱 추가", command=self.add_external_app)
            self.context_menu.add_command(label="🎯 실행 중 앱 추가", command=self.show_running_apps_selector)
            self.context_menu.add_command(label="⚙️ 앱 편집/삭제", command=self.manage_external_apps)
            self.context_menu.add_separator()
        
        self.context_menu.add_command(label="🔼 맨 앞으로 가져오기", command=self.bring_to_front)
        self.context_menu.add_command(label="🔽 맨 뒤로 보내기", command=self.send_to_back)
        self.context_menu.add_separator()
        
        self.context_menu.add_command(label="🔄 가로/세로 전환", command=lambda: self.toggle_orientation(False))
        if self.role == "main":
            self.context_menu.add_command(label="❓ 도움말", command=self.show_help_from_json)
            
        self.context_menu.add_separator()
        self.context_menu.add_command(label="🧹 설정된 경로 Clear", command=self.clear_saved_path, state=menu_state)
        self.context_menu.add_command(label="❌ 종료", command=self.destroy_app)
        
        self.context_menu.post(event.x_root, event.y_root)

    def manage_external_apps(self):
        win = ctk.CTkToplevel(self)
        win.title("앱 관리"); win.geometry("350x450"); win.attributes("-topmost", True)
        
        scroll = ctk.CTkScrollableFrame(win); scroll.pack(fill="both", expand=True, padx=10, pady=(10, 60))
        
        check_vars = []
        for path in self.custom_apps:
            var = tk.BooleanVar()
            f = ctk.CTkFrame(scroll, fg_color="transparent"); f.pack(fill="x", pady=2)
            cb = ctk.CTkCheckBox(f, text=os.path.basename(path), variable=var, font=("Segoe UI", 12))
            cb.pack(side="left", padx=5)
            check_vars.append((path, var))

        def delete_selected():
            to_remove = [p for p, v in check_vars if v.get()]
            if not to_remove: return
            if messagebox.askyesno("삭제 확인", f"선택한 {len(to_remove)}개의 앱을 삭제하시겠습니까?"):
                for p in to_remove: self.custom_apps.remove(p)
                self.save_config(); self.refresh_custom_buttons(); win.destroy()

        btn_del = ctk.CTkButton(win, text="선택 삭제", fg_color="#C0392B", hover_color="#A93226", command=delete_selected)
        btn_del.place(relx=0.5, rely=0.9, anchor="center")

    def show_help_from_json(self):
        help_win = ctk.CTkToplevel(self)
        help_win.title("도움말"); help_win.geometry("400x350"); help_win.attributes("-topmost", True)
        
        title_label = ctk.CTkLabel(help_win, text="도움말", font=("Segoe UI", 16, "bold"))
        title_label.pack(pady=10)

        txt = ctk.CTkTextbox(help_win, font=("Consolas", 12), corner_radius=5)
        txt.pack(fill="both", expand=True, padx=15, pady=15)

        if os.path.exists(HELP_FILE):
            with open(HELP_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                title_label.configure(text=data.get("title", "도움말"))
                txt.insert("0.0", data.get("content", "내용이 없습니다."))
        else:
            txt.insert("0.0", "help_data.json 파일을 찾을 수 없습니다.\n기본 가이드를 확인하세요.")
        
        txt.configure(state="disabled")

    def drag_window(self, event):
        if getattr(self, '_is_draggable', False):
            self.attributes("-alpha", 0.7)
            mx, my = int(event.x_root), int(event.y_root)
            nx, ny = mx - self.offset_x, my - self.offset_y
            snap = 30; ww, wh = self.winfo_width(), self.winfo_height()
            
            for m in self.cached_monitors:
                if m.x <= mx <= m.x + m.width and m.y <= my <= m.y + m.height:
                    if abs(nx - m.x) < snap: nx = m.x
                    elif abs(nx + ww - (m.x + m.width)) < snap: nx = m.x + m.width - ww
                    if abs(ny - m.y) < snap: ny = m.y
                    elif abs(ny + wh - (m.y + m.height)) < snap: ny = m.y + m.height - wh
                    break
            self.geometry(f"+{int(nx)}+{int(ny)}")

    def on_bg_release(self, event):
        if hasattr(self, '_drag_timer') and self._drag_timer: self.after_cancel(self._drag_timer)
        self.attributes("-alpha", 1.0)
        self.last_x, self.last_y = self.winfo_x(), self.winfo_y()   # 마우스 드래그를 마친 현재 위치를 먼저 저장
        self.toggle_orientation(keep_state=True)                    # 모니터 간 배율(DPI) 차이로 인해 잘린 UI를 현재 모니터 환경에 맞춰 새로고침하여 꽉 채움
        self.save_config()
        self._is_draggable = False
        self.configure(cursor="arrow")

    def click_window(self, event):
        self.offset_x, self.offset_y = event.x_root - self.winfo_x(), event.y_root - self.winfo_y()

    def click_handle(self, event):
        self.click_window(event)
        self._is_draggable = True
        self.configure(cursor="fleur")

    def on_bg_click(self, event):
        self._is_draggable = False
        self._drag_timer = self.after(300, lambda: setattr(self, '_is_draggable', True) or self.configure(cursor="fleur"))

    def load_config(self):
        self.bat_folder = ""; self.custom_apps = []; self.orientation = "vertical"
        self.last_x, self.last_y = 100, 100
        self.launch_sub1 = False # [추가]
        self.launch_sub2 = False # [추가]
        
        main_x, main_y = 100, 100
        if os.path.exists("launcher_config_main.json"):
            try:
                with open("launcher_config_main.json", "r", encoding="utf-8") as f:
                    main_data = json.load(f)
                    main_x = main_data.get("last_x", 100)
                    main_y = main_data.get("last_y", 100)
            except: pass

        offset = 40 if self.role == "sub1" else (80 if self.role == "sub2" else 0)
        self.last_x = main_x + offset
        self.last_y = main_y + offset

        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.bat_folder = data.get("bat_folder", "")
                    self.custom_apps = data.get("custom_apps", [])
                    self.orientation = data.get("orientation", "vertical")
                    
                    self.launch_sub1 = data.get("launch_sub1", False) # [추가]
                    self.launch_sub2 = data.get("launch_sub2", False) # [추가]
                    
                    saved_x = data.get("last_x")
                    saved_y = data.get("last_y")
                    
                    if saved_x is not None and saved_y is not None:
                        if self.role != "main" and abs(saved_x - main_x) < 10 and abs(saved_y - main_y) < 10:
                            pass 
                        else:
                            self.last_x = saved_x
                            self.last_y = saved_y
            except: pass

    def save_config(self):
        try:
            data = {"bat_folder": self.bat_folder, "custom_apps": self.custom_apps, "orientation": self.orientation, "last_x": int(self.last_x), "last_y": int(self.last_y)}
            
            # [추가] Main 툴바인 경우 현재 켜져있는 Sub 툴바 상태 확인 및 기록
            if self.role == "main":
                import ctypes
                # Sub1 깃발 확인
                h1 = ctypes.windll.kernel32.OpenMutexW(0x00100000, False, "DevToolbar_Sub1")
                data["launch_sub1"] = bool(h1)
                if h1: ctypes.windll.kernel32.CloseHandle(h1) # 메모리 누수 방지
                
                # Sub2 깃발 확인
                h2 = ctypes.windll.kernel32.OpenMutexW(0x00100000, False, "DevToolbar_Sub2")
                data["launch_sub2"] = bool(h2)
                if h2: ctypes.windll.kernel32.CloseHandle(h2)
                
            with open(CONFIG_FILE, "w", encoding="utf-8") as f: json.dump(data, f, indent=4)
        except: pass

    def validate_position(self):
        try:
            if not any(m.x <= self.last_x <= m.x + m.width - 50 and m.y <= self.last_y <= m.y + m.height - 50 for m in self.cached_monitors):
                self.last_x = self.last_y = 100
        except: pass

    def toggle_orientation(self, keep_state=False):
        print("keep_state: ", keep_state)
        print("direction mode: ", self.orientation)
        if not keep_state: self.orientation = "vertical" if self.orientation == "horizontal" else "horizontal"; self.save_config()
        for w in self.main_frame.winfo_children(): w.pack_forget()
        if self.orientation == "horizontal":
            self.drag_handle.pack(side="left", padx=(10, 0))
            self.folder_label.pack(side="left", padx=(5, 10))
            for b in [self.btn_auto, self.btn_clean, self.btn_log] + self.custom_buttons: b.pack(side="left", padx=3, pady=8)
            self.btn_close.pack(side="right", padx=(1, 5))
            if self.role == "main": # Main 전용 버튼 패킹
                self.btn_minimize.pack(side="right", padx=1)
                self.btn_setting.pack(side="right", padx=(5, 1))
        else:
            self.drag_handle.pack(side="top", pady=(10, 0))
            self.folder_label.pack(side="top", pady=(5, 10))
            for b in [self.btn_auto, self.btn_clean, self.btn_log] + self.custom_buttons: b.pack(side="top", padx=10, pady=3)
            self.btn_close.pack(side="bottom", padx=5, pady=(1, 10))
            if self.role == "main": # Main 전용 버튼 패킹
                self.btn_minimize.pack(side="bottom", padx=5)
                self.btn_setting.pack(side="bottom", padx=5, pady=(15, 1))
        self.update_idletasks()
        # 2. [핵심] 내부 메인 프레임이 현재 내용물을 다 보여주기 위해 "실제로 필요로 하는" 너비와 높이를 직접 계산
        req_width = self.main_frame.winfo_reqwidth()
        req_height = self.main_frame.winfo_reqheight()        
        # 3. [핵심] CustomTkinter의 현재 모니터 배율(Scale Factor) 가져오기
        scale = self._get_window_scaling()
        # 4. 배율이 중복으로 곱해지는 것을 막기 위해, 스케일 값으로 나누어 '논리적 크기'로 변환
        target_width = int(req_width / scale)
        target_height = int(req_height / scale)
        # 5. 계산된 정확한 크기와 위치 지정
        self.geometry(f"{target_width}x{target_height}+{int(self.last_x)}+{int(self.last_y)}")
        
        print("scale: ", scale)
        print(f"강제 리사이징 완료: {req_width}x{req_height}, 위치: x({self.last_x}), y({self.last_y})")
        print("")

    def refresh_custom_buttons(self):
        for b in self.custom_buttons: b.destroy()
        self.custom_buttons.clear(); self.custom_images.clear()
        for p in self.custom_apps:
            name = os.path.basename(p).replace(".exe", "")
            btn = None
            if IconExtractor and os.path.exists(p):
                try:
                    t_ico = os.path.join(tempfile.gettempdir(), f"{name}_icon.ico")
                    if not os.path.exists(t_ico): IconExtractor(p).export_icon(t_ico)
                    img = Image.open(t_ico)
                    icon_img = ctk.CTkImage(light_image=img, dark_image=img, size=(30, 30))
                    self.custom_images.append(icon_img)
                    btn = self.add_raw_button("", lambda path=p: os.startfile(path), "#1E272E", 55, 55, image=icon_img)
                except: pass
            if not btn: btn = self.add_raw_button(f"🖥️\n{name[:5]}", lambda path=p: os.startfile(path), "#16A085", 55, 55)
            ToolTip(btn).text = name
            self.custom_buttons.append(btn)
        self.toggle_orientation(True)

    def show_running_apps_selector(self):
        win = ctk.CTkToplevel(self); win.attributes("-topmost", True); win.title("앱 추가")
        scroll = ctk.CTkScrollableFrame(win); scroll.pack(fill="both", expand=True)
        seen = set()
        for w in gw.getAllWindows():
            if w.title:
                try:
                    _, pid = win32process.GetWindowThreadProcessId(w._hWnd)
                    path = psutil.Process(pid).exe()
                    if path not in seen and "Windows" not in path:
                        seen.add(path)
                        ctk.CTkButton(scroll, text=w.title[:25], command=lambda p=path: self.add_app(p, win)).pack(pady=2, fill="x")
                except: continue

    def add_app(self, p, win):
        if p not in self.custom_apps: self.custom_apps.append(p); self.save_config(); self.refresh_custom_buttons()
        if win: win.destroy()

    def add_external_app(self):
        p = filedialog.askopenfilename(filetypes=[("Exe", "*.exe")]); 
        if p: self.add_app(p, None)

    def force_set_path(self):
        p = filedialog.askdirectory(); 
        if p and os.path.exists(os.path.join(p, BAT_FILENAME)): 
            self.bat_folder = p; self.save_config(); self.update_folder_label(); self.update_button_states()

    def clear_saved_path(self):
        self.bat_folder = ""; self.save_config(); self.update_folder_label(); self.update_button_states()

    def update_button_states(self):
        is_valid = bool(self.bat_folder and os.path.exists(os.path.join(self.bat_folder, BAT_FILENAME)))
        
        for b in self.action_buttons:
            if is_valid:
                b["widget"].configure(state="normal", fg_color=b["color"], text_color="white")
            else:
                b["widget"].configure(state="disabled", fg_color="#34495E", text_color="#7F8C8D")

    def minimize_to_tray(self):
        self.withdraw()
        
        # 1. 사용할 이미지 파일 이름 지정 (파이썬 파일과 같은 경로에 두세요)
        icon_path = "tray_icon.png" # .ico 파일이라면 "tray_icon.ico"로 변경
        
        if os.path.exists(icon_path):
            # 2. 이미지 파일이 존재하면 해당 이미지를 트레이 아이콘으로 로드
            img = Image.open(icon_path)
        else:
            # 3. 이미지 파일이 없을 경우를 대비한 기본 이모지 렌더링 (안전 장치)
            icon_size = (64, 64)
            img = Image.new('RGBA', icon_size, color=(0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            try:
                font = ImageFont.truetype("seguiemj.ttf", 50)
            except IOError:
                font = ImageFont.load_default()
            d.text((icon_size[0]/2, icon_size[1]/2), "😚", font=font, fill="white", anchor="mm")

        # 아이콘 실행
        self.icon = pystray.Icon("DevToolbar", img, "Dev Toolbar", pystray.Menu(
            item('열기', lambda i: (i.stop(), self.after(100, self.deiconify)), default=True),
            pystray.Menu.SEPARATOR, # 구분선
            item('🚀 Auto Build', lambda i: self.run_build()),
            item('🧹 Clean Build', lambda i: self.run_clean()),
            item('🗑 Log 정리', lambda i: self.run_clear_logs()),
            pystray.Menu.SEPARATOR,
            item('➕ 앱 추가', lambda i: self.after(0, self.add_external_app)),
            item('⚙️ 앱 편집/삭제', lambda i: self.after(0, self.manage_external_apps)),
            pystray.Menu.SEPARATOR,
            item('위치 초기화', self.reset_position), 
            item('❌ 종료', self.destroy_app)
        ))
        threading.Thread(target=self.icon.run, daemon=True).start()

    def reset_position(self, i=None):
        self.last_x = self.last_y = 100; self.save_config()
        if i: i.stop()
        self.after(100, lambda: (self.deiconify(), self.geometry("+100+100")))

    def destroy_app(self, i=None):
        if i: i.stop()
        self.destroy(); os._exit(0)

    def run_build(self): self.exec_bat("build")
    def run_clean(self): self.exec_bat("clean")
    def run_clear_logs(self): self.exec_bat("c_log")
    def exec_bat(self, a):
        if self.bat_folder: subprocess.Popen(["cmd.exe", "/c", BAT_FILENAME, "gui_mode", a], cwd=self.bat_folder, creationflags=subprocess.CREATE_NEW_CONSOLE)

    def force_show_on_taskbar(self):
        # 윈도우 OS의 API를 직접 호출하기 위해 ctypes 사용
        import ctypes
        try:
            # 현재 창의 고유 ID(핸들)를 가져옵니다.
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
            
            # 윈도우 창 스타일을 정의하는 상수들
            GWL_EXSTYLE = -20
            WS_EX_APPWINDOW = 0x00040000
            WS_EX_TOOLWINDOW = 0x00000080
            
            # 현재 창의 스타일을 읽어옵니다.
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            # '숨겨진 도구 창' 속성을 지우고, '일반 앱 창(작업표시줄 표시)' 속성을 덮어씌웁니다.
            style = (style & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
            
            # 변경된 스타일을 윈도우가 인식하게 하려면 창을 1초의 찰나 동안 숨겼다 띄워야 합니다.
            self.wm_withdraw()
            self.wm_deiconify()
            self.attributes("-topmost", True) # 다시 맨 앞으로 끌어올림
        except Exception as e:
            print("작업표시줄 등록 중 에러 발생:", e)
    def check_main_alive(self):
        import ctypes
        # Main 툴바의 깃발(Mutex)이 존재하는지 확인합니다.
        handle = ctypes.windll.kernel32.OpenMutexW(0x00100000, False, "DevToolbar_Main")
        if not handle:
            # 깃발이 없다면 Main이 종료된 것이므로 나도 스스로 종료합니다.
            self.destroy_app()
        else:
            # 깃발이 있다면 안심하고 핸들을 닫은 뒤, 2초(2000ms) 뒤에 다시 감시합니다.
            ctypes.windll.kernel32.CloseHandle(handle)
            self.after(2000, self.check_main_alive)
    

if __name__ == "__main__":
    app = MiniLauncher(); app.mainloop()