import axios from "axios";

export const RESTAURANTS = [{ id: "florya-tasfirin", name: "Florya Taşfırın" }, { id: "etiler-marmaris", name: "Etiler Marmaris" }, { id: "durumtir", name: "Dürümtır" }];
export const restaurantName = (id) => (id === "all" ? "Tüm restoranlar" : RESTAURANTS.find((r) => r.id === id)?.name || "");

export const getRestaurant = () => { const saved = localStorage.getItem("gokboss-restaurant"); return saved === "all" || RESTAURANTS.some((r) => r.id === saved) ? saved : RESTAURANTS[0].id; };
export const setRestaurant = (id) => { localStorage.setItem("gokboss-restaurant", id); axios.defaults.headers.common["X-Restaurant"] = id; };
setRestaurant(getRestaurant());

export const errorText = (e, fallback) => { const d = e?.response?.data?.detail; return typeof d === "string" ? d : fallback; };
