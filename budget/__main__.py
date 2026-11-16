import argparse
import json
from .store import Store
from .analysis import Analysis
from .tools import Tools
from .chat import Chat


def main():
    parser = argparse.ArgumentParser(description='Local budget analysis / Yerel bütçe analizi')
    parser.add_argument('--db', default='budget.sqlite')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('init')
    history = sub.add_parser('import-history', help='Import monthly household XLSX ledger once')
    history.add_argument('file')
    tool = sub.add_parser('tool')
    tool.add_argument('name')
    tool.add_argument('arguments', help='JSON arguments; money values must be strings')
    chat = sub.add_parser('chat')
    chat.add_argument('--model', default='qwen3.5:9b', help='Installed Ollama model (default: qwen3.5:9b)')
    chat.add_argument('--language', choices=['en','tr'], default='en')
    web = sub.add_parser('web', help='Start the local upload dashboard')
    web.add_argument('--port', type=int, default=8000)
    web.add_argument('--model', default='qwen3.5:9b')
    args = parser.parse_args()
    if args.command == 'web':
        import uvicorn
        from .web import create_app
        uvicorn.run(create_app(args.db, args.model), host='127.0.0.1', port=args.port)
        return
    store = Store(args.db)
    tools = Tools(Analysis(store))
    try:
        if args.command == 'init':
            print('Database initialized; no transactions added / Veritabanı hazır; işlem eklenmedi')
        elif args.command == 'import-history':
            from .history import import_history
            print(json.dumps(import_history(store, args.file), ensure_ascii=False, indent=2))
        elif args.command == 'tool':
            print(json.dumps(tools.call(args.name,json.loads(args.arguments)),ensure_ascii=False,indent=2))
        else:
            session = Chat(tools,args.model,args.language)
            while True:
                try:
                    text = input('> ')
                except EOFError:
                    break
                if text.strip() in {'/quit','/exit'}:
                    break
                try:
                    print(json.dumps(session.ask(text),ensure_ascii=False,indent=2))
                except (ValueError,RuntimeError) as exc:
                    print(str(exc))
    finally:
        store.db.close()


if __name__ == '__main__':
    main()
