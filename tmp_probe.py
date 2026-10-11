import pathlib, tempfile
d = tempfile.mkdtemp()
f = pathlib.Path(d) / 'x'
f.write_text('x')
try:
    open(str(f / 'memories.json'))
except Exception as e:
    print(type(e).__name__, '|', e)

