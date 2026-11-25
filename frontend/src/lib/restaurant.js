import axios from "axios";

export const RESTAURANTS = [];
export const session = { role: "" };
export const restaurantName = (id) => (id === "all" ? "Tüm restoranlar" : RESTAURANTS.find((r) => r.id === id)?.name || "");
export const setRestaurantsList = (list) => { RESTAURANTS.splice(0, RESTAURANTS.length, ...list); };
export const needsPin = (id) => (id === "all" ? RESTAURANTS.some((r) => r.has_pin) : Boolean(RESTAURANTS.find((r) => r.id === id)?.has_pin));

export const getRestaurant = () => { const saved = localStorage.getItem("gokboss-restaurant"); return (saved === "all" && session.role === "admin") || RESTAURANTS.some((r) => r.id === saved) ? saved : RESTAURANTS[0]?.id || ""; };
export const setRestaurant = (id) => { localStorage.setItem("gokboss-restaurant", id); axios.defaults.headers.common["X-Restaurant"] = id; };
export const setRestaurantKey = (token) => { if (token) axios.defaults.headers.common["X-Restaurant-Key"] = token; else delete axios.defaults.headers.common["X-Restaurant-Key"]; };

export const errorText = (e, fallback) => { const d = e?.response?.data?.detail; return typeof d === "string" ? d : fallback; };
