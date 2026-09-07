import { defineStore } from 'pinia'

export const useUiStore = defineStore('ui', {
  state: () => ({ drawerOpen: false }),
  actions: {
    toggleDrawer() {
      this.drawerOpen = !this.drawerOpen
    },
  },
})
