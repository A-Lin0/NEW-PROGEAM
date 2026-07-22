"""排查技术问答和案例分析环节的重复题目"""
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

# 获取最新一场有对话记录的面试
cur.execute("""
    SELECT i.id, i.position, i.target_company_name, i.created_at
    FROM interviews i
    WHERE EXISTS (
        SELECT 1 FROM agent_sessions s WHERE s.session_id = CAST(i.id AS TEXT)
    )
    ORDER BY i.created_at DESC LIMIT 1
""")
iv = cur.fetchone()
if not iv:
    print("无面试记录")
    conn.close()
    exit()

print("=" * 80)
print(f"最新面试: id={iv['id']}")
print(f"  position={iv['position']} | target_company={iv['target_company_name']} | created_at={iv['created_at']}")
print()

# 查询 agent_sessions
cur.execute("SELECT id, session_id, target_agent, session_status FROM agent_sessions WHERE session_id=? ORDER BY created_at DESC", (str(iv['id']),))
sessions = cur.fetchall()
for s in sessions:
    cur.execute("SELECT role, content, seq, agent_key, event_type FROM agent_dialogue_records WHERE session_pk=? ORDER BY seq ASC", (s['id'],))
    dialogs = cur.fetchall()
    print(f"--- [{s['target_agent']}] 对话记录数: {len(dialogs)} ---")
    for d in dialogs:
        content = (d['content'] or '')
        if len(content) > 200:
            content = content[:200] + '...'
        print(f"  [seq={d['seq']}] role={d['role']} | event_type={d['event_type']}: {content}")
    print()

# 查询 Redis 中的 question_records
print("=" * 80)
print("Redis 中的 question_records")
print("=" * 80)
import asyncio
async def check_redis():
    import redis.asyncio as aioredis
    rc = aioredis.from_url("redis://interview_redis:6379/0")
    key = f"session:{iv['id']}"
    val = await rc.get(key)
    if val:
        ctx = json.loads(val)
        qr = ctx.get('question_records', [])
        print(f"question_records 数量: {len(qr)}")
        for i, rec in enumerate(qr):
            q = (rec.get('question') or '')[:120]
            print(f"  [{i+1}] stage={rec.get('stage')} | score={rec.get('score')} | skipped={rec.get('skipped')} | q={q}")
        # 检查重复题
        print()
        print("=== 重复题检测 ===")
        from collections import defaultdict
        stage_questions = defaultdict(list)
        for i, rec in enumerate(qr):
            stage = rec.get('stage', 'unknown')
            q = rec.get('question', '')[:80]
            stage_questions[stage].append((i, q))
        for stage, items in stage_questions.items():
            if len(items) > 1:
                print(f"\n阶段 {stage} 共 {len(items)} 题:")
                for idx, q in items:
                    print(f"  [{idx+1}] {q}")
                # 检测相似度
                qs = [q for _, q in items]
                for i in range(len(qs)):
                    for j in range(i+1, len(qs)):
                        # 简单字符级相似度
                        set1, set2 = set(qs[i]), set(qs[j])
                        if set1 and set2:
                            jaccard = len(set1 & set2) / len(set1 | set2)
                            print(f"  相似度[{i+1} vs {j+1}]: Jaccard={jaccard:.2f}")
    await rc.close()

asyncio.run(check_redis())
conn.close()
