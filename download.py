import requests
import threading
import os
import hashlib
import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext, messagebox
import time
import ctypes

# 开启高DPI适配（解决模糊、分辨率低）
if os.name == 'nt':
    ctypes.windll.shcore.SetProcessDpiAwareness(2)

lock = threading.Lock()

class MultiThreadDownloader:
    def __init__(self, url, save_path, thread_num=8, retry=3, gui_callback=None):
        self.url = url
        self.save_path = save_path
        self.thread_num = thread_num
        self.retry = retry
        self.file_size = 0
        self.support_range = False
        self.gui_callback = gui_callback
        self.stop_flag = False
        self.last_time = time.time()
        self.last_bytes = 0

    def log(self, msg):
        if self.gui_callback:
            self.gui_callback("log", msg)

    def update_progress(self, val):
        now = time.time()
        with lock:
            if self.gui_callback:
                self.gui_callback("progress", val)
                delta_t = now - self.last_time
                if delta_t >= 0.5:
                    speed = self.last_bytes / delta_t
                    self.gui_callback("speed", speed)
                    self.last_bytes = 0
                    self.last_time = now
                else:
                    self.last_bytes += val

    def get_file_info(self):
        resp = requests.head(self.url, timeout=10, allow_redirects=True)
        self.file_size = int(resp.headers.get("Content-Length", 0))
        self.support_range = resp.headers.get("Accept-Ranges", "none") == "bytes"
        self.log(f"文件总大小：{self.file_size / 1024 / 1024:.2f} MB，支持分片：{self.support_range}")

    def get_local_size(self):
        if os.path.exists(self.save_path):
            return os.path.getsize(self.save_path)
        return 0

    def download_chunk(self, start, end):
        for _ in range(self.retry):
            if self.stop_flag:
                return
            try:
                headers = {"Range": f"bytes={start}-{end}"}
                resp = requests.get(self.url, headers=headers, timeout=15, stream=True)
                pos = start
                with open(self.save_path, "rb+") as f:
                    f.seek(pos)
                    for chunk in resp.iter_content(1024 * 64):
                        if self.stop_flag:
                            return
                        if chunk:
                            f.write(chunk)
                            self.update_progress(len(chunk))
                            pos += len(chunk)
                return
            except Exception as e:
                self.log(f"分片 {start}-{end} 异常，重试：{str(e)}")
        self.log(f"分片 {start}-{end} 多次重试失败！")

    def calc_md5(self):
        self.log("开始MD5校验...")
        md5 = hashlib.md5()
        with open(self.save_path, "rb") as f:
            while chunk := f.read(1024 * 1024):
                md5.update(chunk)
        res = md5.hexdigest()
        self.log(f"MD5值：{res}")
        return res

    def run(self):
        try:
            self.get_file_info()
            local_size = self.get_local_size()

            if self.file_size <= 0:
                self.log("无法获取文件大小，切换单线程下载，不支持断点")
                resp = requests.get(self.url, stream=True)
                with open(self.save_path, "wb") as f:
                    for chunk in resp.iter_content(1024 * 64):
                        if self.stop_flag:
                            return
                        f.write(chunk)
                        self.update_progress(len(chunk))
                self.log("✅ 单线程下载完成")
                if self.gui_callback:
                    self.gui_callback("finish", "")
                return

            if not self.support_range:
                self.log("服务器不支持Range分片，切换单线程，无断点")
                resp = requests.get(self.url, stream=True)
                with open(self.save_path, "wb") as f:
                    for chunk in resp.iter_content(1024 * 64):
                        if self.stop_flag:
                            return
                        f.write(chunk)
                        self.update_progress(len(chunk))
                self.log("✅ 单线程下载完成")
                if self.gui_callback:
                    self.gui_callback("finish", "")
                return

            if 0 < local_size < self.file_size:
                self.log(f"检测到未完成文件，断点续传，已下载 {local_size / 1024 / 1024:.2f} MB")
            elif local_size == self.file_size:
                self.log("文件已下载完成，开始校验MD5")
                self.calc_md5()
                if self.gui_callback:
                    self.gui_callback("finish", "")
                return
            else:
                with open(self.save_path, "wb") as f:
                    f.truncate(self.file_size)
                self.log("新建空白占位文件")

            self.log("启动多线程分片下载")
            chunk_size = self.file_size // self.thread_num
            threads = []
            for i in range(self.thread_num):
                seg_start = i * chunk_size
                seg_end = self.file_size - 1 if i == self.thread_num - 1 else seg_start + chunk_size - 1
                if seg_end < local_size:
                    continue
                real_start = max(seg_start, local_size)
                t = threading.Thread(target=self.download_chunk, args=(real_start, seg_end), daemon=True)
                t.start()
                threads.append(t)
            for t in threads:
                t.join()
            if self.stop_flag:
                self.log("⏹️ 下载已手动停止，下次可以断点续传")
            else:
                self.log("✅ 全部分片下载完成，开始校验MD5")
                self.calc_md5()
                if self.gui_callback:
                    self.gui_callback("finish", "")
        except Exception as e:
            self.log(f"下载异常：{str(e)}")

# -------------------------- GUI 高DPI清晰版 --------------------------
class DownloadGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("浮川多线程下载器")
        self.root.geometry("1000x640")
        self.root.resizable(False, False)
        self.root.configure(bg="#f5f7fa")
        self.downloader = None
        self.download_total = 0
        self.downloaded = 0

        style = ttk.Style()
        style.configure("TProgressbar", thickness=20)

        # 标题
        title_label = tk.Label(root, text="浮川多线程下载器", font=("微软雅黑", 20, "bold"), bg="#f5f7fa", fg="#2c3e50")
        title_label.grid(row=0, column=0, columnspan=4, pady=(16, 24))

        label_width = 10
        # 下载链接
        tk.Label(root, text="下载链接：", font=("微软雅黑", 12), bg="#f5f7fa", fg="#34495e", width=label_width, anchor="w")\
            .grid(row=1, column=0, sticky="w", padx=20, pady=8)
        self.url_entry = ttk.Entry(root, font=("微软雅黑", 12))
        self.url_entry.grid(row=1, column=1, columnspan=3, padx=(0,20), pady=8, sticky="ew")

        # 保存位置
        tk.Label(root, text="保存位置：", font=("微软雅黑", 12), bg="#f5f7fa", fg="#34495e", width=label_width, anchor="w")\
            .grid(row=2, column=0, sticky="w", padx=20, pady=8)
        self.path_entry = ttk.Entry(root, font=("微软雅黑", 12))
        self.path_entry.grid(row=2, column=1, padx=(0,8), pady=8, sticky="ew")
        ttk.Button(root, text="选择文件", command=self.select_save_path).grid(row=2, column=2, padx=6, pady=8)

        # 线程数量
        tk.Label(root, text="线程数量：", font=("微软雅黑", 12), bg="#f5f7fa", fg="#34495e", width=label_width, anchor="w")\
            .grid(row=3, column=0, sticky="w", padx=20, pady=8)
        self.thread_entry = ttk.Entry(root, width=14, font=("微软雅黑", 12))
        self.thread_entry.insert(0, "8")
        self.thread_entry.grid(row=3, column=1, sticky="w", padx=(0,6), pady=8)

        # 下载进度
        tk.Label(root, text="下载进度：", font=("微软雅黑", 12), bg="#f5f7fa", fg="#34495e", width=label_width, anchor="w")\
            .grid(row=4, column=0, sticky="w", padx=20, pady=10)
        self.progress = ttk.Progressbar(root, style="TProgressbar")
        self.progress.grid(row=4, column=1, padx=(0,8), pady=10, sticky="ew")
        self.percent_label = tk.Label(root, text="0%", width=8, font=("微软雅黑",12), bg="#f5f7fa")
        self.percent_label.grid(row=4, column=2, padx=4)
        self.speed_label = tk.Label(root, text="速度：0 B/s", width=20, font=("微软雅黑",12), bg="#f5f7fa", fg="#27ae60")
        self.speed_label.grid(row=4, column=3, padx=8)

        # 大小信息
        self.size_label = tk.Label(root, text="0.00 MB / 0.00 MB", font=("微软雅黑", 12), bg="#f5f7fa", fg="#7f8c8d")
        self.size_label.grid(row=5, column=1, padx=0, pady=(0,10), sticky="w")

        # 按钮区域
        btn_frame = tk.Frame(root, bg="#f5f7fa")
        btn_frame.grid(row=6, column=1, columnspan=2, pady=14)
        self.start_btn = tk.Button(btn_frame, text="开始下载", command=self.start_download,
                                   bg="#27ae60", fg="white", font=("微软雅黑",12,"bold"), width=16, height=1)
        self.start_btn.pack(side=tk.LEFT, padx=12)
        self.stop_btn = tk.Button(btn_frame, text="停止下载", command=self.stop_download,
                                   bg="#e74c3c", fg="white", font=("微软雅黑",12,"bold"), width=16, height=1, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=12)

        # 日志
        tk.Label(root, text="运行日志：", font=("微软雅黑", 12), bg="#f5f7fa", fg="#34495e", width=label_width, anchor="nw")\
            .grid(row=7, column=0, sticky="nw", padx=20, pady=8)
        self.log_text = scrolledtext.ScrolledText(root, font=("Consolas",10))
        self.log_text.grid(row=7, column=1, columnspan=3, padx=(0,20), pady=8, sticky="nsew")

        root.grid_columnconfigure(1, weight=1)
        root.grid_rowconfigure(7, weight=1)

    def format_speed(self, byte_per_sec):
        if byte_per_sec < 1024:
            return f"{byte_per_sec:.1f} B/s"
        elif byte_per_sec < 1024 * 1024:
            return f"{byte_per_sec / 1024:.1f} KB/s"
        else:
            return f"{byte_per_sec / 1024 / 1024:.2f} MB/s"

    def format_size(self, byte):
        if byte < 1024 * 1024:
            return f"{byte / 1024:.2f} KB"
        else:
            return f"{byte / 1024 / 1024:.2f} MB"

    def select_save_path(self):
        file_path = filedialog.asksaveasfilename(title="另存为")
        if file_path:
            self.path_entry.delete(0, tk.END)
            self.path_entry.insert(0, file_path)

    def gui_callback(self, typ, data):
        if typ == "log":
            self.log_text.insert(tk.END, f"{time.strftime('%H:%M:%S')} | {data}\n")
            self.log_text.see(tk.END)
        elif typ == "progress":
            self.downloaded += data
            if self.download_total > 0:
                percent = self.downloaded / self.download_total * 100
                self.progress["value"] = percent
                self.percent_label.config(text=f"{percent:.1f}%")
                self.size_label.config(text=f"{self.format_size(self.downloaded)} / {self.format_size(self.download_total)}")
        elif typ == "speed":
            self.speed_label.config(text=f"速度：{self.format_speed(data)}")
        elif typ == "finish":
            messagebox.showinfo("完成", "✅ 文件下载完成！")

    def start_download(self):
        url = self.url_entry.get().strip()
        save_path = self.path_entry.get().strip()
        try:
            thread_num = int(self.thread_entry.get())
        except ValueError:
            self.gui_callback("log", "线程数必须是数字！")
            return
        if not url or not save_path:
            self.gui_callback("log", "链接和保存路径不能为空！")
            return

        self.log_text.delete(1.0, tk.END)
        self.progress["value"] = 0
        self.downloaded = 0
        self.percent_label.config(text="0%")
        self.size_label.config(text="0.00 MB / 0.00 MB")
        self.speed_label.config(text="速度：0 B/s")
        self.downloader = MultiThreadDownloader(url, save_path, thread_num=thread_num, gui_callback=self.gui_callback)
        try:
            resp = requests.head(url, timeout=10, allow_redirects=True)
            self.download_total = int(resp.headers.get("Content-Length", 0))
        except Exception:
            self.download_total = 0
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        t = threading.Thread(target=self.downloader.run, daemon=True)
        t.start()
        self.gui_callback("log", "✅ 已启动下载任务")

    def stop_download(self):
        if self.downloader:
            self.downloader.stop_flag = True
            self.gui_callback("log", "⏹️ 正在发送停止信号...")
            def wait_stop():
                t.join()
                self.start_btn.config(state=tk.NORMAL)
                self.stop_btn.config(state=tk.DISABLED)
                self.speed_label.config(text="速度：0 B/s")
            threading.Thread(target=wait_stop, daemon=True).start()

if __name__ == "__main__":
    root = tk.Tk()
    app = DownloadGUI(root)
    root.mainloop()
