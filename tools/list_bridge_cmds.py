import os
root = r"C:\Users\HP\AppData\Roaming\MetaQuotes\Terminal\Common\Files"
for dirpath, dirnames, filenames in os.walk(root):
    for fn in filenames:
        if fn.lower().endswith('.cmd'):
            print(os.path.join(dirpath, fn))
