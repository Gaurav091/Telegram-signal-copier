# VPS Deployment Steps — Telegram Signal Copier

Follow these steps to build, install, authorize, and run the Telegram Signal Copier on your Remote Desktop (RDP) VPS environment.

---

### Step 1: Build the Installer Executable
1. Open the project in VS Code on your build machine (local environment).
2. Press `Ctrl + Shift + B` (or go to **Terminal** -> **Run Build Task...**).
3. Select the task: **`Build Telegram Signal Copier Installer (EXE)`**.
4. This runs the build pipeline which:
   - Compiles the source code with PyInstaller.
   - Bundles the portable Tesseract OCR engine, Flet GUI elements, and virtual environment dependencies.
   - Compiles the final setup installer using Inno Setup.
5. Once completed, your installer executable will be generated at:
   `d:\Github repos\Telegram signal Copier\Output\TelegramSignalCopierSetup.exe` (or in the `Output/` subdirectory of your project root).

---

### Step 2: Transfer and Install on RDP VPS
1. Connect to your VPS via **Remote Desktop Connection (RDP)**.
2. Copy `TelegramSignalCopierSetup.exe` from your local build machine and paste it onto your VPS desktop.
3. Double-click the setup file and complete the installation wizard.
4. By default, the application installs to:
   `C:\Program Files\Telegram Signal Copier`

---

### Step 3: Configure Credentials (.env file)
1. On the VPS, navigate to your AppData roaming configuration directory:
   `C:\Users\Administrator\AppData\Roaming\TelegramSignalCopier`
2. Open the `.env` file in Notepad or any text editor.
3. Update the credentials with your specific parameters:
   * `TELEGRAM_API_ID` (your API ID from my.telegram.org)
   * `TELEGRAM_API_HASH` (your API Hash from my.telegram.org)
   * `TELEGRAM_PHONE_NUMBER` (your international format phone number, e.g., `+1234567890`)
   * `TELEGRAM_SOURCES` (comma-separated list of target signal chats/channels, e.g. `Gold Channel::123456789`)
   * `MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER` (your MT5 broker credentials)
   * `MT5_SYMBOL_SUFFIX` (your broker suffix, e.g. `m` for XAUUSDm, `c` for cent account, or blank if standard)
4. Save and close the `.env` file.

---

### Step 4: Login to Telegram & Start Listener
1. Open the installation folder on the VPS:
   `C:\Program Files\Telegram Signal Copier`
2. Double-click `TelegramSignalCopier.exe` to launch the controller app.
3. Click **`Telegram Login`**:
   - This opens a separate console window.
   - Enter the login code (OTP) sent to your Telegram account.
   - Once successfully logged in, the session file is saved and the console window will close.
4. Click **`Start Listener`**:
   - This launches the listener daemon in a new console window.
   - The logs will populate in real-time, looking similar to:
     ```text
     2026-06-04 08:07:49,235 [INFO] [TG] listener client connected
     2026-06-04 08:07:59,702 [INFO] [TG] source chats resolved: 21
     ```

---

### Step 5: Setup Expert Advisor (EA) in MetaTrader 5
1. Copy the compiled Expert Advisor file `TelegramSignalCopierEA.ex5` (located under the `mt5/Experts/` folder of your project root or downloaded bundle).
2. Open your **MetaTrader 5 terminal** on the VPS.
3. Go to **File** -> **Open Data Folder**.
4. Navigate to `MQL5` -> `Experts` and paste `TelegramSignalCopierEA.ex5` into that folder.
5. In the MT5 Navigator panel, right-click **Experts** and click **Refresh**.
6. Drag `TelegramSignalCopierEA` onto any active chart (e.g., `XAUUSDm` H1).
7. In the EA properties window:
   - Go to the **Common** tab and check **Allow Algo Trading**.
   - Ensure the MT5 global **Algo Trading** button in the top toolbar is green (enabled).
8. Verify that the chart status indicator in the top-right/top-left shows **Connected** and "AutoTrading=ON".
