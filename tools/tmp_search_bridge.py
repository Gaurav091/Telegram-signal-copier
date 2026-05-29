import os
root = r"C:\Users\HP\AppData\Roaming\MetaQuotes\Terminal\Common\Files\TelegramSignalCopierBridge"
query = '982be8b0'
for dirpath, dirnames, filenames in os.walk(root):
    for fn in filenames:
        if query in fn:
            print(os.path.join(dirpath, fn))
