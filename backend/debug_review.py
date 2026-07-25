"""全面排查复盘模块生成异常"""
import sqlite3
import json
import os
os.environ['PYTHONIOENCODING'] = 'utf-8'
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

conn = sqlite3.connect('/app/data/app.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()

print("=" * 80)
print("【1】数据库表结构检查")
print("=" * 80)
# 检查 interviews 表
cur.execute("PRAGMA table_info(interviews)")
cols = cur.fetchall()
print("interviews 表字段:")
for c in cols:
    print(f"  {c['name']} ({c['type']})")

# 检查是否有专门的复盘报告表
cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%review%' OR name LIKE '%report%'")
tables = cur.fetchall()
print(f"\n复盘相关表: {[t['name'] for t in tables]}")

print()
print("=" * 80)
print("【2】最近5场面试记录")
print("=" * 80)
cur.execute("""
    SELECT id, position, target_company_name, overall_score, phase_scores,
           status, created_at, updated_at
    FROM interviews ORDER BY created_at DESC LIMIT 5
""")
for r in cur.fetchall():
    print(f"\nid={r['id']}")
    print(f"  position={r['position']} | target_company={r['target_company_name']}")
    print(f"  overall_score={r['overall_score']} | status={r['status']}")
    print(f"  created_at={r['created_at']} | updated_at={r['updated_at']}")
    ps = r['phase_scores']
    if ps:
        try:
            ps_data = json.loads(ps) if isinstance(ps, str) else ps
            print(f"  phase_scores={ps_data}")
        except:
            print(f"  phase_scores(raw)={str(ps)[:200]}")

print()
print("=" * 80)
print("【3】最新面试的对话历史")
print("=" * 80)
cur.execute("SELECT id FROM interviews ORDER BY created_at DESC LIMIT 1")
iv = cur.fetchone()
if iv:
    iv_id = str(iv['id'])
    print(f"最新面试ID: {iv_id}")
    cur.execute("SELECT id, session_id, target_agent, session_status FROM agent_sessions WHERE session_id=? ORDER BY created_at DESC", (iv_id,))
    sessions = cur.fetchall()
    for s in sessions:
        cur.execute("SELECT role, content, seq, agent_key, event_type FROM agent_dialogue_records WHERE session_pk=? ORDER BY seq ASC", (s['id'],))
        dialogs = cur.fetchall()
        print(f"\n[{s['target_agent']}] status={s['session_status']} | 对话数={len(dialogs)}")
        for d in dialogs[:3]:
            content = (d['content'] or '')[:150]
            print(f"  [seq={d['seq']}] role={d['role']}: {content}")

print()
print("=" * 80)
print("【4】Redis 中的 session_ctx（含 question_records 和 评分数据）")
print("=" * 80)
import asyncio
async def check_redis():
    import redis.asyncio as aioredis
    rc = aioredis.from_url("redis://interview_redis:6379/0")
    keys = await rc.keys("session:*")
    print(f"Redis session keys: {len(keys)}")
    for key in keys[:3]:
        key_str = key.decode() if isinstance(key, bytes) else key
        val = await rc.get(key)
        if val:
            try:
                ctx = json.loads(val)
                print(f"\n--- {key_str} ---")
                print(f"  session_status: {ctx.get('session_status')}")
                print(f"  total_score: {ctx.get('total_score')}")
                print(f"  stage_scores: {ctx.get('stage_scores')}")
                print(f"  section_scores: {ctx.get('section_scores')}")
                qr = ctx.get('question_records', [])
                print(f"  question_records 数量: {len(qr)}")
                for i, rec in enumerate(qr):
                    q = (rec.get('question') or '')[:60]
                    print(f"    [{i+1}] stage={rec.get('stage')} | score={rec.get('score')} | skipped={rec.get('skipped')} | q={q}")
            except Exception as e:
                print(f"  解析失败: {e}")
    await rc.close()

asyncio.run(check_redis())
conn.close()
