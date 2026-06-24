module.exports = {
  apps : [{
    name   : "asomien-bot",
    script : "main.py",
    interpreter: "venv/Scripts/pythonw.exe",
    args: "--start",
    autorestart: true,
    watch: false
  }]
}
