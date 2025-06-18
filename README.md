# MCP Client

A Flask-based web client for interacting with Model Context Protocol (MCP) filesystem servers. This application provides a modern, user-friendly web interface for exploring and interacting with MCP servers.

## Features

- 🌐 Web-based interface for MCP server interaction
- 🔌 Easy server connection management
- 📂 Directory listing and navigation
- 🛠️ Support for MCP tools and commands
- 💻 Real-time command execution
- 🎨 Modern and responsive UI

## Prerequisites

- Python 3.x
- Flask
- MCP Server (compatible with Model Context Protocol)

## Installation

1. Clone the repository
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Usage

1. Start the Flask application:
   ```bash
   python app.py
   ```

2. Open your browser and navigate to `http://localhost:5000`

3. In the web interface:
   - Enter the MCP server command (default: `node dist/index.js --stdio`)
   - Click "Start Server" to connect
   - Use available commands in the chat interface

## Available Commands

- `/list [path]` - List directory contents (default: Downloads folder)
- `/tools` - Show available MCP tools

## Project Structure

```
mcp_client/
├── app.py              # Main Flask application
├── requirements.txt    # Python dependencies
└── templates/
    └── chat.html      # Web interface template
```

## License

Licensed under the Apache License, Version 2.0. See the [LICENSE](LICENSE) file for details.