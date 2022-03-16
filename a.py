import subprocess

p = subprocess.Popen(["cmd", "/c", "pip list"], shell=True)
p.wait()

p = subprocess.Popen(["cmd", "/c", "pip list"])
p.wait()
