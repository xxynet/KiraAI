<template>
  <div
    class="flex items-start gap-3 rounded-lg px-4 py-3 text-sm"
    :class="level === 'warning'
      ? 'bg-amber-50 dark:bg-amber-900/20 text-amber-800 dark:text-amber-200'
      : 'bg-blue-50 dark:bg-blue-900/20 text-blue-800 dark:text-blue-200'"
  >
    <IconWarning v-if="level === 'warning'" class="w-5 h-5 mt-0.5 shrink-0" />
    <IconInfo v-else class="w-5 h-5 mt-0.5 shrink-0" />
    <div>
      <p v-if="label" class="font-medium">
        <template v-for="(seg, i) in labelSegments" :key="i">
          <a
            v-if="seg.url"
            :href="seg.url"
            target="_blank"
            rel="noopener noreferrer"
            class="underline underline-offset-2 hover:opacity-75"
          >{{ seg.text }}</a>
          <template v-else>{{ seg.text }}</template>
        </template>
      </p>
      <p v-if="hint" class="mt-1 opacity-80 whitespace-pre-line">
        <template v-for="(seg, i) in hintSegments" :key="i">
          <a
            v-if="seg.url"
            :href="seg.url"
            target="_blank"
            rel="noopener noreferrer"
            class="underline underline-offset-2 hover:opacity-75"
          >{{ seg.text }}</a>
          <template v-else>{{ seg.text }}</template>
        </template>
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { IconInfo, IconWarning } from '@/components/icons'
import { linkifySegments } from '@/utils/linkify'

const props = defineProps<{
  level?: string
  label?: string
  hint?: string
}>()

const labelSegments = computed(() => linkifySegments(props.label ?? ''))
const hintSegments = computed(() => linkifySegments(props.hint ?? ''))
</script>
