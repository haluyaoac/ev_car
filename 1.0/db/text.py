from sqlalchemy import create_engine, text, inspect
import sys
# 把项目路径放到 sys.path 最前面，确保优先导入本地 config.py
sys.path.insert(0, r'C:\Users\14367\Desktop\vscode\ev_car')
import importlib
import config

def main():
    print("导入的 config 模块路径:", getattr(config, "__file__", "<unknown>"))
    print("config 中可用属性示例：", [k for k in dir(config) if not k.startswith("_")][:30])
    if not hasattr(config, "DB_URL"):
        print("错误：导入的 config 模块没有 DB_URL。")
        print("请确认：")
        print("  1) c:\\Users\\14367\\Desktop\\vscode\\ev_car\\config.py 文件存在且包含 DB_URL 定义；")
        print("  2) 没有其他名为 config 的已安装包覆盖本地模块；")
        print("解决方案：可以把本地 config.py 重命名为 ev_config.py 并在此处 import ev_config。")
        return

    print("使用 DB_URL:", config.DB_URL)
    engine = create_engine(config.DB_URL, future=True, pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            ver = conn.execute(text("SELECT VERSION()")).scalar()
            print("MySQL 版本:", ver)
            inspector = inspect(engine)
            tables = inspector.get_table_names()
            print("数据库表:", tables)
            if "cars" in tables:
                cnt = conn.execute(text("SELECT COUNT(*) FROM cars")).scalar()
                print("cars 表行数:", cnt)
            else:
                print("未找到 cars 表（表可能尚未创建）")
    except Exception as e:
        print("连接或查询失败：", e)

if __name__ == "__main__":
    # 确保如果你在调试过程中修改了 config，重新载入它
    importlib.reload(config)
    main()