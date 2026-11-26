export const MENU_LANGS = [
  { code: "tr", label: "TR", name: "Türkçe" },
  { code: "en", label: "EN", name: "English" },
  { code: "ar", label: "AR", name: "العربية" },
  { code: "ru", label: "RU", name: "Русский" },
];

export const MENU_TEXT = {
  tr: { welcome: "Restoranımıza hoş geldiniz", kicker: "— Taş fırın · Dürüm · Lahmacun —", menu: "M E N Ü", pick: "Bir kategori seçin", items: "ürün", back: "Kategoriler", swipe: "Kategoriler arasında kaydırarak da geçebilirsiniz", footer: "Afiyet olsun", error: "Menü yüklenemedi, lütfen tekrar deneyin.", empty: "Menü yakında burada.", translating: "Menü çevriliyor…",
    chat: { button: "Menüye sor", title: "Menü Asistanı", subtitle: "Menümüzle ilgili her şeyi sorabilirsiniz", greeting: "Hoş geldiniz! Size menümüzden ne önermemi istersiniz?", placeholder: "Sorunuzu yazın…", suggestions: ["Ne önerirsiniz?", "Acısız seçenekler neler?", "En hesaplı ürün hangisi?"] } },
  en: { welcome: "Welcome to our restaurant", kicker: "— Stone oven · Wraps · Lahmacun —", menu: "M E N U", pick: "Choose a category", items: "items", back: "Categories", swipe: "You can also swipe between categories", footer: "Enjoy your meal", error: "The menu could not be loaded, please try again.", empty: "The menu will be here soon.", translating: "Translating the menu…",
    chat: { button: "Ask the menu", title: "Menu Assistant", subtitle: "Ask anything about our menu", greeting: "Welcome! What would you like me to recommend?", placeholder: "Type your question…", suggestions: ["What do you recommend?", "Which dishes are not spicy?", "What is the most affordable dish?"] } },
  ar: { welcome: "أهلاً بكم في مطعمنا", kicker: "— فرن حجري · لفائف · لحم بعجين —", menu: "القائمة", pick: "اختر فئة", items: "أصناف", back: "الفئات", swipe: "يمكنك أيضاً السحب للتنقل بين الفئات", footer: "بالهناء والشفاء", error: "تعذّر تحميل القائمة، يرجى المحاولة مرة أخرى.", empty: "القائمة ستكون هنا قريباً.", translating: "جارٍ ترجمة القائمة…",
    chat: { button: "اسأل عن القائمة", title: "مساعد القائمة", subtitle: "اسأل أي شيء عن قائمتنا", greeting: "أهلاً بك! ماذا تريد أن أقترح عليك؟", placeholder: "اكتب سؤالك…", suggestions: ["ماذا تقترح؟", "ما الأطباق غير الحارة؟", "ما أرخص طبق؟"] } },
  ru: { welcome: "Добро пожаловать в наш ресторан", kicker: "— Каменная печь · Дюрюм · Лахмаджун —", menu: "М Е Н Ю", pick: "Выберите категорию", items: "блюд", back: "Категории", swipe: "Между категориями можно листать свайпом", footer: "Приятного аппетита", error: "Не удалось загрузить меню, попробуйте ещё раз.", empty: "Меню скоро появится.", translating: "Переводим меню…",
    chat: { button: "Спросить о меню", title: "Помощник по меню", subtitle: "Спросите что угодно о нашем меню", greeting: "Добро пожаловать! Что вам порекомендовать?", placeholder: "Напишите вопрос…", suggestions: ["Что вы посоветуете?", "Какие блюда не острые?", "Какое блюдо самое недорогое?"] } },
};

export const initialMenuLang = () => {
  const saved = localStorage.getItem("menu-lang");
  if (MENU_TEXT[saved]) return saved;
  const nav = (navigator.language || "tr").slice(0, 2);
  return MENU_TEXT[nav] ? nav : "tr";
};
