# PNG 去背轉換 App MVP 規劃

## 1. 目標

建立一個用 Python 開發的 Windows 桌面 App，讓客戶可以直接雙擊 `.exe` 使用，不需要安裝 Python。

MVP 先只做最核心流程：

- 選擇 1 張 JPG / JPEG / PNG 圖片
- 自動去背
- 輸出透明背景 PNG
- 讓客戶直接在 Windows 上使用 `.exe`

## 2. MVP 定位

這一版不要做成 Flask API，也不要先做成網站。

原因很直接：

- 你的目標是交付給客戶使用
- 客戶通常不會自己跑 Python 環境
- `.exe` 桌面程式比本機架 API 更符合交付需求

所以 MVP 應該改成：

`Python GUI App` + `PyInstaller 打包 exe`

## 3. 技術選型

- Python 3.10+
- `rembg`：AI 去背
- `Pillow`：圖片讀寫與格式處理
- `tkinter`：內建 GUI，MVP 足夠，部署最簡單
- `PyInstaller`：把 Python 程式打包成 Windows `.exe`

建議安裝：

```bash
pip install rembg pillow pyinstaller
```

如果 `rembg` 需要補齊推論依賴，再安裝：

```bash
pip install onnxruntime
```

## 4. 交付形式

最終交付物不是 `.py`，而是：

- `PngFactory.exe`

客戶使用方式：

1. 雙擊開啟 `PngFactory.exe`
2. 選擇圖片
3. 點擊「開始去背」
4. 儲存輸出的 PNG

## 5. MVP 功能範圍

### 必做

- 單張圖片選擇
- 去背處理
- 存成 PNG
- 基本錯誤提示
- Windows exe 打包

### 先不做

- 帳號登入
- 雲端上傳
- 資料庫
- 批次多張處理
- 拖拉上傳
- 圖片編輯器
- 前後預覽比對

## 6. 系統流程

```text
使用者選圖
   ↓
Python 桌面 GUI
   ↓
rembg 去背
   ↓
輸出透明背景 PNG
   ↓
使用者另存檔案
```

## 7. 建議專案結構

```text
png-factory/
├─ main.py
├─ app/
│  ├─ ui.py
│  ├─ remover.py
│  └─ file_service.py
├─ assets/
│  └─ icon.ico
├─ output/
├─ requirements.txt
└─ build_exe.bat
```

## 8. 核心實作方向

### `remover.py`

```python
from rembg import remove


def remove_background(input_bytes: bytes) -> bytes:
    return remove(input_bytes)
```

### `main.py` MVP 概念

```python
import tkinter as tk
from tkinter import filedialog, messagebox
from pathlib import Path

from app.remover import remove_background


def choose_and_convert():
    file_path = filedialog.askopenfilename(
        filetypes=[("Image Files", "*.jpg *.jpeg *.png")]
    )
    if not file_path:
        return

    try:
        input_path = Path(file_path)
        output_path = input_path.with_name(f"{input_path.stem}_no_bg.png")

        with open(input_path, "rb") as f:
            output_data = remove_background(f.read())

        with open(output_path, "wb") as f:
            f.write(output_data)

        messagebox.showinfo("完成", f"已輸出：{output_path}")
    except Exception as exc:
        messagebox.showerror("錯誤", str(exc))


root = tk.Tk()
root.title("PNG 去背轉換工具")
root.geometry("360x180")

button = tk.Button(root, text="選擇圖片並去背", command=choose_and_convert)
button.pack(expand=True)

root.mainloop()
```

## 9. 打包成 exe

### 基本指令

```bash
pyinstaller --noconfirm --onefile --windowed --name PngFactory main.py
```

打包完成後，輸出通常會在：

```text
dist/PngFactory.exe
```

### 如果你要加圖示

```bash
pyinstaller --noconfirm --onefile --windowed --icon assets/icon.ico --name PngFactory main.py
```

## 10. 很重要的交付注意事項

### 1. `rembg` 模型問題

`rembg` 在某些情況下第一次執行會需要模型檔。如果你要交付給客戶，不能假設客戶環境會自己下載成功。

所以正式版要確認其中一種做法：

- 在打包前先把模型準備好
- 測試 exe 是否能在沒裝 Python 的乾淨 Windows 環境直接運作
- 必要時把模型檔一起包進發行版本

### 2. 不要把 MVP 做成 Web

如果做 Flask：

- 客戶還要開本機服務
- 還要處理瀏覽器、port、環境問題
- 不符合「直接交付 exe」這件事

所以這案子的正確起點是桌面版。

### 3. 先做單張，再考慮批次

批次轉換會牽涉：

- 多檔案選取
- 命名規則
- 處理中狀態
- 失敗重試
- UI 卡頓

MVP 不需要先把這些複雜度帶進來。

## 11. 建議開發順序

1. 先完成 `main.py` 單張去背
2. 在本機直接跑 `.py` 測試成功
3. 再用 `PyInstaller` 打包成 `.exe`
4. 在另一台沒裝 Python 的 Windows 機器測試
5. 確認交付包內容後再給客戶

## 12. MVP 驗收標準

- 可以開啟桌面 App
- 可以選擇圖片
- 可以成功去背
- 可以輸出透明背景 PNG
- `.exe` 在客戶 Windows 環境可直接執行

## 13. 結論

這個專案的 MVP 應該明確定義成：

**用 Python 開發的 Windows 去背工具，並能打包成 `.exe` 交付客戶。**

不是 Flask API，也不是網站先行。

下一步最合理的是直接開始做這 3 個檔案：

- `main.py`
- `app/remover.py`
- `requirements.txt`

如果你要，我下一步可以直接幫你把這個 MVP 專案骨架做出來，連同可打包 `.exe` 的版本一起建好。
