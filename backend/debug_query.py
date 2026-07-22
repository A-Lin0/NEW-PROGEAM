import sqlite3
import json
import os
os.environ['PYTHONIOENCODING'] = 'utf-8'

conn = sqlite3.connect('/app/data/app.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# 查询最近3场面试
cur.execute("SELECT id, position, target_company_name, company_id, created_at FROM interviews ORDER BY created_at DESC LIMIT 3")
interviews = cur.fetchall()

for iv in interviews:
    print("=" * 80)
    print(f"面试ID: {iv['id']}")
    print(f"岗位: {iv['position']}")
    print(f"目标公司: {iv['target_company_name']}")
    print(f"公司ID: {iv['company_id']}")
    print(f"创建时间: {iv['created_at']}")
    print()

    # 查询 agent_sessions
    cur.execute("SELECT id, session_id, target_agent, session_status FROM agent_sessions WHERE session_id=? ORDER BY created_at DESC", (str(iv['id']),))
    sessions = cur.fetchall()
    print(f"agent_sessions 记录数: {len(sessions)}")
    for s in sessions:
        print(f"  pk={s['id']} | target_agent={s['target_agent']} | status={s['session_status']}")

    # 查询对话记录（通过 session_pk 关联）
    for s in sessions:
        cur.execute("SELECT role, content, seq, agent_key, event_type FROM agent_dialogue_records WHERE session_pk=? ORDER BY seq ASC", (s['id'],))
        dialogs = cur.fetchall()
        print(f"  --- {s['target_agent']} 对话记录数: {len(dialogs)} ---")
        for d in dialogs[:6]:  # 前6条
            content = (d['content'] or '')
            if len(content) > 300:
                content = content[:300] + '...'
            print(f"    [seq={d['seq']}] role={d['role']} | agent_key={d['agent_key']} | event_type={d['event_type']}")
            print(f"    内容: {content}")
            print()

conn.close()
