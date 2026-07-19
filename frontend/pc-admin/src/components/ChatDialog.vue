<template>
  <div class="chat-dialog">
    <div class="messages" ref="msgRef">
      <div v-for="(msg, i) in messages" :key="i" :class="['msg', msg.role]">
        <div class="avatar">{{ msg.role === 'system' ? '🤖' : '👤' }}</div>
        <div class="content">{{ msg.content }}</div>
      </div>
      <div v-if="streaming" class="msg system">
        <div class="avatar">🤖</div>
        <div class="content streaming">{{ streamText }}<span class="cursor">|</span></div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, nextTick } from 'vue'

const props = defineProps({
  messages: { type: Array, default: () => [] },
  streamText: { type: String, default: '' },
  streaming: { type: Boolean, default: false },
})

const msgRef = ref(null)

watch(
  () => [props.messages.length, props.streamText],
  () => {
    nextTick(() => {
      if (msgRef.value) {
        msgRef.value.scrollTop = msgRef.value.scrollHeight
      }
    })
  },
  { deep: true }
)
</script>

<style scoped>
.chat-dialog { display: flex; flex-direction: column; }
.messages { flex: 1; overflow-y: auto; padding: 10px; min-height: 300px; }
.msg { display: flex; margin-bottom: 14px; }
.msg.user { flex-direction: row-reverse; }
.msg .avatar { width: 32px; height: 32px; display: flex; align-items: center; justify-content: center; border-radius: 50%; margin: 0 8px; flex-shrink: 0; background: #eee; font-size: 16px; }
.msg .content { max-width: 75%; padding: 10px 14px; border-radius: 10px; line-height: 1.6; white-space: pre-wrap; }
.msg.system .content { background: #f0f0f0; }
.msg.user .content { background: #409eff; color: #fff; }
.cursor { animation: blink 1s infinite; }
@keyframes blink { 0%, 50% { opacity: 1; } 51%, 100% { opacity: 0; } }
</style>
