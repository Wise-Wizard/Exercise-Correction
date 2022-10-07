import { createRouter, createWebHistory } from "vue-router";

const router = createRouter({
    history: createWebHistory(import.meta.env.BASE_URL),
    routes: [
        {
            path: "/",
            name: "Mediapipe",
            component: () => import("../views/Mediapipe.vue"),
        },
    ],
});

export default router;