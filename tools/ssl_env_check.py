import sys
import os
import glob
import traceback

print('sys.executable=', sys.executable)
print('sys.version=', sys.version)
print('platform=', sys.platform)

# Try importing ssl
try:
    import ssl
    print('SSL_IMPORT_OK')
    print('ssl.OPENSSL_VERSION =', getattr(ssl, 'OPENSSL_VERSION', 'UNKNOWN'))
    print('ssl.__file__ =', getattr(ssl, '__file__', 'UNKNOWN'))
except Exception as exc:
    print('SSL_IMPORT_ERROR:', repr(exc))
    traceback.print_exc()

# Inspect venv layout (assumes venv root is parent of Scripts/)
venv_root = os.path.abspath(os.path.join(os.path.dirname(sys.executable), '..'))
print('venv_root =', venv_root)

patterns = [
    os.path.join(venv_root, '**', '_ssl*.pyd'),
    os.path.join(venv_root, '**', '_ssl*.dll'),
    os.path.join(venv_root, '**', 'libssl*.dll'),
    os.path.join(venv_root, '**', 'libcrypto*.dll'),
    os.path.join(venv_root, 'DLLs', '*.dll'),
    os.path.join(venv_root, 'Scripts', '*.dll'),
]

for p in patterns:
    matches = glob.glob(p, recursive=True)
    print(f'PATTERN: {p} -> {len(matches)} match(es)')
    for m in matches[:20]:
        print('  ', m)

# Show a few environment hints
print('PATH (first 400 chars)=', os.environ.get('PATH', '')[:400])
print('sys.path sample:')
for p in sys.path[:10]:
    print('  ', p)

# Check system python (if available) for ssl support
try:
    import subprocess
    out = subprocess.check_output(['python', '-c', 'import ssl; print(getattr(ssl, "OPENSSL_VERSION", "UNKNOWN"))'], stderr=subprocess.STDOUT, text=True, timeout=5)
    print('system python ssl check ->', out.strip())
except Exception as e:
    print('system python ssl check failed ->', repr(e))
