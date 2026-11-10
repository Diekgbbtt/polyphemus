(() => {
  var __webpack_require__ = {};
  __webpack_require__.p = "/cdn/assets/";
  __webpack_require__.u = (id) => {
    var hashes = { 5: "abc123" };
    return "chunks/feature-" + id + "." + hashes[id] + ".mjs";
  };
  (self.webpackChunkfixture = self.webpackChunkfixture || []).push([[5], {
    "w5a": (module, exports, __webpack_require__) => {
      module.exports = __webpack_require__("w5b");
    },
    "w5b": (module, exports) => {
      module.exports = "webpack5";
    }
  }]);
})();
