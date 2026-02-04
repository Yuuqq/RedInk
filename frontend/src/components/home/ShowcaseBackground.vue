<template>
  <!-- Apple-like mesh background (lighter + faster than image grid) -->
  <div class="home-background" aria-hidden="true">
    <div class="home-bg home-bg-mesh"></div>
    <div class="home-bg home-bg-noise"></div>
    <div class="home-bg home-bg-vignette"></div>
  </div>
</template>

<script setup lang="ts">
</script>

<style scoped>
/* Background container */
.home-background {
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100dvh;
  z-index: -1;
  overflow: hidden;
}

.home-bg {
  position: absolute;
  inset: 0;
}

.home-bg-mesh::before {
  content: "";
  position: absolute;
  inset: -22%;
  background:
    radial-gradient(600px 420px at 18% 6%, var(--bg-glow-1), transparent 60%),
    radial-gradient(680px 460px at 86% 14%, var(--bg-glow-2), transparent 58%),
    radial-gradient(520px 520px at 72% 82%, rgba(10, 132, 255, 0.10), transparent 60%),
    radial-gradient(520px 460px at 10% 84%, rgba(94, 92, 230, 0.09), transparent 62%);
  filter: blur(28px) saturate(125%);
  transform: translate3d(0, 0, 0);
  animation: mesh-float 18s ease-in-out infinite;
}

.home-bg-noise {
  opacity: 0.08;
  mix-blend-mode: overlay;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='160' height='160'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.9' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='160' height='160' filter='url(%23n)' opacity='.7'/%3E%3C/svg%3E");
  background-size: 160px 160px;
}

.home-bg-vignette {
  background:
    radial-gradient(1200px 700px at 20% -10%, transparent 40%, var(--bg-body) 100%),
    radial-gradient(1100px 660px at 90% 0%, transparent 45%, var(--bg-body) 100%),
    linear-gradient(to bottom, rgba(0, 0, 0, 0.00) 0%, rgba(0, 0, 0, 0.02) 55%, rgba(0, 0, 0, 0.06) 100%);
  pointer-events: none;
}

@keyframes mesh-float {
  0% {
    transform: translate3d(-1.5%, -1%, 0) scale(1.02);
  }
  50% {
    transform: translate3d(1.2%, 1.6%, 0) scale(1.05);
  }
  100% {
    transform: translate3d(-1.5%, -1%, 0) scale(1.02);
  }
}

@media (prefers-reduced-motion: reduce) {
  .home-bg-mesh::before {
    animation: none;
  }
}
</style>
