import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import { setupAutoSave } from './stores/generator'

// Styles
import './assets/css/variables.css'
import './assets/css/base.css'
import './assets/css/components.css'
import './assets/css/home.css'
import './assets/css/history.css'

const app = createApp(App)

app.use(createPinia())
setupAutoSave()
app.use(router)

app.mount('#app')
