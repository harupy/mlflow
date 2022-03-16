import subprocess

p = subprocess.Popen(["cmd", "/c", 'pip install "requirements\\lint-requirements.txt"'], shell=True)
p.wait()

p = subprocess.Popen(
    ["cmd", "/c", 'pip install "requirements\\lint-requirements.txt"'], shell=False
)
p.wait()
