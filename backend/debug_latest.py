"""全面排查：查询最新面试记录、对话历史、Redis会话上下文"""
import sqlite3
import json
import os
os.environ['PYTHONIOENCODING'] = 'utf-8'
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

print("=" * 80)
print("【1】数据库：最近5场面试记录")
print("=" * 80)
conn = sqlite3.connect('/app/data/app.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()
cur.execute("SELECT id, position, target_company_name, company_id, created_at FROM interviews ORDER BY created_at DESC LIMIT 5")
for r in cur.fetchall():
    print(f"  id={r['id']} | position={r['position']} | target_company_name={r['target_company_name']} | company_id={r['company_id']} | created_at={r['created_at']}")

print()
print("=" * 80)
print("【2】最近3场面试的对话历史（agent_dialogue_records）")
print("=" * 80)
cur.execute("SELECT id, position, target_company_name, created_at FROM interviews ORDER BY created_at DESC LIMIT 3")
interviews = cur.fetchall()
for iv in interviews:
    print(f"\n--- 面试 {iv['id']} | target_company={iv['target_company_name']} | position={iv['position']} | created_at={iv['created_at']} ---")
    cur.execute("SELECT id, session_id, target_agent, session_status FROM agent_sessions WHERE session_id=? ORDER BY created_at DESC", (str(iv['id']),))
    sessions = cur.fetchall()
    for s in sessions:
        cur.execute("SELECT role, content, seq, agent_key, event_type FROM agent_dialogue_records WHERE session_pk=? ORDER BY seq ASC", (s['id'],))
        dialogs = cur.fetchall()
        print(f"  [{s['target_agent']}] 对话记录数: {len(dialogs)}")
        for d in dialogs[:4]:
            content = (d['content'] or '')[:250]
            print(f"    [seq={d['seq']}] role={d['role']}: {content}")

print()
print("=" * 80)
print("【3】Redis 中的会话上下文（session:*）")
print("=" * 80)
import asyncio
async def check_redis():
    import redis.asyncio as aioredis
    rc = aioredis.from_url("redis://interview_redis:6379/0")
    keys = await rc.keys("session:*")
    print(f"Redis session keys 数量: {len(keys)}")
    for key in keys[:5]:
        key_str = key.decode() if isinstance(key, bytes) else key
        val = await rc.get(key)
        if val:
            try:
                ctx = json.loads(val)
                print(f"\n--- {key_str} ---")
                print(f"  session_status: {ctx.get('session_status')}")
                print(f"  current_stage: {ctx.get('current_stage')}")
                print(f"  target_position: {ctx.get('target_position')}")
                print(f"  target_company: {ctx.get('target_company')}")
                ua = ctx.get('user_assets', {})
                print(f"  user_assets.target_company: {ua.get('target_company')}")
                print(f"  user_assets.target_position: {ua.get('target_position')}")
                cc = ctx.get('company_ctx', {}) or {}
                print(f"  company_ctx.company_name: {cc.get('company_name')}")
                print(f"  company_ctx.has_company: {cc.get('has_company')}")
                hist = ctx.get('history', [])
                print(f"  history 长度: {len(hist)}")
                if hist:
                    print(f"  history[0]: {str(hist[0])[:150]}")
            except Exception as e:
                print(f"  解析失败: {e}")
    await rc.close()

asyncio.run(check_redis())

print()
print("=" * 80)
print("【4】文件持久化数据（/data/interview_history/）")
print("=" * 80)
import glob
files = glob.glob('/data/interview_history/*.json')
print(f"文件数量: {len(files)}")
for f in files[:3]:
    try:
        with open(f, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
        print(f"\n--- {f} ---")
        print(f"  target_company: {data.get('target_company')}")
        print(f"  target_position: {data.get('target_position')}")
        ua = data.get('user_assets', {})
        print(f"  user_assets.target_company: {ua.get('target_company')}")
        cc = data.get('company_ctx', {}) or {}
        print(f"  company_ctx.company_name: {cc.get('company_name')}")
        hist = data.get('history', [])
        print(f"  history 长度: {len(hist)}")
        if hist:
            print(f"  history[0]: {str(hist[0])[:150]}")
            if len(hist) > 1:
                print(f"  history[1]: {str(hist[1])[:150]}")
    except Exception as e:
        print(f"  读取失败: {e}")

conn.close()
