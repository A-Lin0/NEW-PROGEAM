<template>
  <div class="streaming-text">
    <span v-for="(char, i) in displayText" :key="i">{{ char }}</span>
    <span v-if="isStreaming" class="cursor">|</span>
  </div>
</template>

<script setup>
import { ref, watch, onUnmounted } from 'vue'

const props = defineProps({
  text: { type: String, default: '' },
  speed: { type: Number, default: 30 },
})

const displayText = ref('')
const isStreaming = ref(false)
let index = 0
let timer = null

function startTyping(text) {
  index = displayText.value.length
  isStreaming.value = true
  const chars = text.slice(index).split('')

  function typeNext() {
    if (index < text.length) {
      displayText.value += text[index]
      index++
      timer = setTimeout(typeNext, props.speed)
    } else {
      isStreaming.value = false
    }
  }
  typeNext()
}

watch(() => props.text, (newText) => {
  if (newText.length > displayText.value.length) {
    startTyping(newText)
  } else if (newText.length < displayText.value.length) {
    displayText.value = newText
    index = newText.length
  }
})

onUnmounted(() => {
  if (timer) clearTimeout(timer)
})
</script>

<style scoped>
.streaming-text {
  white-space: pre-wrap;
  line-height: 1.8;
}
.cursor {
  animation: blink 1s infinite;
}
@keyframes blink {
  0%, 50% { opacity: 1; }
  51%, 100% { opacity: 0; }
}
</style>
