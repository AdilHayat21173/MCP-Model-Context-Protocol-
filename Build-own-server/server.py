from fastmcp import FastMCP
from main import app

mcp = FastMCP.from_fastapi(
    app=app,
    name="Cost Manager"
)

if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=8080, path="/mcp")