// Shared behaviour for the defect lab.
//
// The "user" query parameter selects a defect profile, mirroring how
// saucedemo.com injects defects per account. State is carried in the URL
// (not localStorage) because file:// origins have no reliable storage.

const PRODUCTS = [
  { id: "backpack",   name: "Sauce Labs Backpack",        price: 29.99, img: "img/backpack.svg" },
  { id: "bike-light", name: "Sauce Labs Bike Light",      price: 9.99,  img: "img/bike-light.svg" },
  { id: "bolt-shirt", name: "Sauce Labs Bolt T-Shirt",    price: 15.99, img: "img/bolt-shirt.svg" },
  { id: "jacket",     name: "Sauce Labs Fleece Jacket",   price: 49.99, img: "img/jacket.svg" },
  { id: "onesie",     name: "Sauce Labs Onesie",          price: 7.99,  img: "img/onesie.svg" },
  { id: "red-shirt",  name: "Test.allTheThings() T-Shirt", price: 15.99, img: "img/red-shirt.svg" },
];

// Which defects each profile carries. Deliberately includes defects this tool
// is NOT expected to catch — a lab that only contains catchable defects proves
// nothing.
const PROFILES = {
  standard:    {},
  problem: {
    wrongImages:   true,   // D-1: every product shows the same wrong picture
    lastNameEats:  true,   // D-2: checkout last-name field silently drops input
    sortIsNoop:    true,   // D-3: sort control changes nothing
    badgeNoUpdate: true,   // D-4: add-to-cart works but the badge never updates
    throwsOnLoad:  true,   // D-5: uncaught TypeError during inventory render
  },
  slow:        { delayMs: 1500 },   // D-6: inventory renders late
  locked:      {},
};

function qs(name, fallback) {
  const v = new URLSearchParams(location.search).get(name);
  return v === null ? fallback : v;
}

function profile() {
  return PROFILES[qs("user", "standard")] || {};
}

function carry(path, extra) {
  const p = new URLSearchParams(location.search);
  Object.entries(extra || {}).forEach(([k, v]) => p.set(k, v));
  return path + "?" + p.toString();
}

function money(n) {
  return "$" + n.toFixed(2);
}
