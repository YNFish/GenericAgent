
$env:PORTABLE_DEV_ROOT = "C:\Users\xpc\GenericAgent\.portable"
$env:GENERICAGENT_HOME = "C:\Users\xpc\GenericAgent"
$env:UV_PYTHON_INSTALL_DIR = "C:\Users\xpc\GenericAgent\.portable\uv-python"
$env:UV_CACHE_DIR = "C:\Users\xpc\GenericAgent\.portable\uv-cache"
$env:UV_DEFAULT_INDEX = "https://pypi.tuna.tsinghua.edu.cn/simple"
$env:PIP_INDEX_URL = "https://pypi.tuna.tsinghua.edu.cn/simple"
$env:PATH = "C:\Users\xpc\GenericAgent\.portable\bin;C:\Users\xpc\GenericAgent\.portable\uv-python\cpython-3.12-windows-x86_64-none;C:\Users\xpc\GenericAgent\.portable\uv-python\cpython-3.12-windows-x86_64-none\Scripts;C:\Users\xpc\GenericAgent\.portable\tools\PortableGit\bin;C:\Users\xpc\GenericAgent\.portable\tools\PortableGit\usr\bin;$env:PATH"
Write-Host "Activated GenericAgent portable env: $env:GENERICAGENT_HOME" -ForegroundColor Green
