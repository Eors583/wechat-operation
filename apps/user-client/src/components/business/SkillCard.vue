<script setup lang="ts">
import type { Skill } from '@/api/types'
import AppButton from '@/components/base/AppButton.vue'

defineProps<{ skill: Skill; busy?: boolean }>()
defineEmits<{ detail: []; toggle: [enabled: boolean]; edit: [] }>()
</script>

<template>
  <q-card class="skill-card surface-card" flat>
    <q-card-section class="skill-card__top">
      <div class="skill-card__icon">
        <q-icon :name="skill.scope === 'official' ? 'description' : 'edit_note'" size="28px" />
      </div>
      <q-btn flat round dense icon="more_horiz" aria-label="技能操作">
        <q-menu
          ><q-list>
            <q-item clickable v-close-popup @click="$emit('detail')"
              ><q-item-section>查看详情</q-item-section></q-item
            >
            <q-item v-if="skill.scope === 'personal'" clickable v-close-popup @click="$emit('edit')"
              ><q-item-section>编辑技能</q-item-section></q-item
            >
          </q-list></q-menu
        >
      </q-btn>
    </q-card-section>
    <q-card-section class="skill-card__body">
      <h2>{{ skill.name }}</h2>
      <p>{{ skill.description }}</p>
      <div class="skill-card__tags">
        <q-chip dense>{{ skill.category }}</q-chip
        ><q-chip dense>{{ skill.scope === 'official' ? '官方技能' : '我的技能' }}</q-chip>
      </div>
    </q-card-section>
    <q-card-actions align="right">
      <AppButton
        :variant="skill.enabled ? 'primary' : 'outline'"
        :icon="skill.enabled ? 'check' : 'add'"
        :label="skill.enabled ? '已启用' : '启用技能'"
        :loading="busy"
        @click="$emit('toggle', !skill.enabled)"
      />
    </q-card-actions>
  </q-card>
</template>

<style scoped lang="scss">
.skill-card {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  min-width: 0;
  min-height: 252px;
  box-shadow: none;

  &__top {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  &__icon {
    display: grid;
    place-items: center;
    width: 54px;
    height: 54px;
    color: var(--app-action-primary);
    background: var(--app-action-soft);
    border-radius: 10px;
  }

  &__body {
    min-width: 0;

    h2 {
      margin: 0 0 8px;
      font-size: 19px;
      overflow-wrap: anywhere;
    }
    p {
      margin: 0;
      color: var(--app-text-secondary);
      overflow-wrap: anywhere;
    }
  }

  &__tags {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    margin-top: 18px;
  }
}
</style>
