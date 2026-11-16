# Clickable demos (sample data, nothing saved)
Builds single-file demos of the admin and teacher panels from the real panel code, with a mock API.
```
cd tools/demo && mkdir -p out && python3 gen_demo.py && python3 gen_tdemo.py
```
Output: `out/admin-demo.html`, `out/teacher-demo.html` (open in a browser).
