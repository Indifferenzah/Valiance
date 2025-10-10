with open('ticket.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

with open('ticket.py', 'w', encoding='utf-8') as f:
    for line in lines:
        if not line.strip().startswith('#'):
            f.write(line)
