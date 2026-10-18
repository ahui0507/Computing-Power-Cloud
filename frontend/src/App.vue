<template>
  <router-view />
  <AdminFaultAlerts />
</template>

<script setup lang="ts">
import AdminFaultAlerts from '@/components/AdminFaultAlerts.vue'
</script>

<style scoped>
#app {
  width: 100%;
  height: 100vh;
}
</style>

