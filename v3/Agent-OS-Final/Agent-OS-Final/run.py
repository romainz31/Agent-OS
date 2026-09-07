from agentos.manager import Manager

def show_notifications(manager):
    for n in manager.drain_notifications(): print(f"\n[MANAGER] {n}")

def main():
    print("="*64);print("AGENT-OS FINAL — MANAGER");print("="*64);print("\nCommandes : status | tasks | approvals | memory | oui | non | quit\n")
    manager=Manager()
    try:
        while True:
            show_notifications(manager)
            try:message=input("TOI > ")
            except EOFError:break
            if message.strip().lower()=="quit":break
            response=manager.handle(message)
            if response:print("\nMANAGER >");print(response);print()
            show_notifications(manager)
    except KeyboardInterrupt:print("\nArrêt demandé.")
    finally:print("\nArrêt du Manager...");manager.shutdown();show_notifications(manager)
if __name__=="__main__":main()
