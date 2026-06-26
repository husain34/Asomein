module.exports = {
  apps : [{
    name   : "asomien-bot",
    script : "main.py",
    interpreter: "venv/Scripts/pythonw.exe",
    args: "--start",
    autorestart: true,
    watch: false
  },
  {
    name   : "asomien-dashboard",
    script : "web_dashboard/server.py",
    interpreter: "venv/Scripts/pythonw.exe",
    autorestart: true,
    watch: false
  }]
}
