/* Standalone binding for the host WebUI CustomSelect presentation and interaction. */
(function () {
  "use strict";

  var widgets = [];
  var opened = null;

  function svg(path, size) {
    var icon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    icon.setAttribute("viewBox", "0 0 24 24");
    icon.setAttribute("width", size);
    icon.setAttribute("height", size);
    icon.setAttribute("fill", "none");
    icon.setAttribute("stroke", "currentColor");
    icon.setAttribute("stroke-width", "2");
    icon.setAttribute("stroke-linecap", "round");
    icon.setAttribute("stroke-linejoin", "round");
    icon.setAttribute("aria-hidden", "true");
    var line = document.createElementNS("http://www.w3.org/2000/svg", "path");
    line.setAttribute("d", path);
    icon.appendChild(line);
    return icon;
  }

  function CustomSelect(select) {
    this.select = select;
    this.activeIndex = -1;
    this.options = [];
    this.wrapper = document.createElement("div");
    this.wrapper.className = "custom-select";
    select.before(this.wrapper);
    this.wrapper.appendChild(select);
    this.label = document.querySelector('label[for="' + CSS.escape(select.id) + '"]');
    this.trigger = document.createElement("button");
    this.trigger.type = "button";
    this.trigger.id = select.id + "-trigger";
    this.trigger.className = "custom-select-trigger";
    this.trigger.setAttribute("role", "combobox");
    this.trigger.setAttribute("aria-haspopup", "listbox");
    this.trigger.setAttribute("aria-expanded", "false");
    this.text = document.createElement("span");
    this.text.className = "custom-select-label";
    var content = document.createElement("span");
    content.className = "custom-select-content";
    content.appendChild(this.text);
    var arrow = document.createElement("span");
    arrow.className = "custom-select-arrow";
    arrow.appendChild(svg("m6 9 6 6 6-6", "20"));
    this.trigger.append(content, arrow);
    this.wrapper.appendChild(this.trigger);
    this.menu = document.createElement("div");
    this.menu.id = select.id + "-listbox";
    this.menu.className = "custom-select-options";
    this.menu.setAttribute("role", "listbox");
    this.trigger.setAttribute("aria-controls", this.menu.id);
    document.body.appendChild(this.menu);
    if (this.label) {
      this.label.htmlFor = this.trigger.id;
      if (this.label.id) {
        this.trigger.setAttribute("aria-labelledby", this.label.id);
        this.menu.setAttribute("aria-labelledby", this.label.id);
      }
    }
    select.hidden = true;
    select.tabIndex = -1;
    select.setAttribute("aria-hidden", "true");
    var self = this;
    this.trigger.addEventListener("click", function () {
      if (opened === self) self.close();
      else self.open();
    });
    this.trigger.addEventListener("keydown", function (event) { self.keydown(event); });
    this.menu.addEventListener("pointerdown", function (event) { event.preventDefault(); });
    select.addEventListener("change", function () { self.sync(); });
    select.addEventListener("invalid", function (event) {
      event.preventDefault();
      self.trigger.setAttribute("aria-invalid", "true");
      self.trigger.focus();
    });
    this.observer = new MutationObserver(function () { self.sync(); });
    this.observer.observe(select, { childList: true, subtree: true, characterData: true, attributes: true });
    this.sync();
  }

  CustomSelect.prototype.sync = function () {
    var selected = this.select.selectedOptions[0];
    this.options = Array.from(this.select.options);
    this.text.textContent = selected ? selected.textContent : I18N.t("common.select");
    this.trigger.title = selected ? selected.textContent : "";
    this.trigger.disabled = this.select.disabled;
    this.trigger.classList.toggle("disabled", this.select.disabled);
    this.trigger.classList.toggle("has-value", this.select.value !== "");
    this.trigger.classList.toggle("placeholder", this.select.value === "");
    this.trigger.setAttribute("aria-disabled", String(this.select.disabled));
    this.trigger.setAttribute("aria-required", String(this.select.required));
    this.trigger.setAttribute("aria-invalid", String(!this.select.validity.valid));
    if (this.select.hasAttribute("aria-label")) this.trigger.setAttribute("aria-label", this.select.getAttribute("aria-label"));
    if (opened === this) {
      if (this.select.disabled) this.close();
      else {
        this.activeIndex = Math.min(this.activeIndex, this.options.length - 1);
        this.renderOptions();
        this.position();
      }
    }
  };

  CustomSelect.prototype.renderOptions = function () {
    var self = this;
    this.menu.replaceChildren();
    this.options.forEach(function (option, index) {
      var row = document.createElement("div");
      row.id = self.select.id + "-option-" + index;
      row.className = "custom-select-option";
      row.classList.toggle("selected", option.selected);
      row.classList.toggle("active", index === self.activeIndex);
      row.classList.toggle("disabled", option.disabled);
      row.setAttribute("role", "option");
      row.setAttribute("aria-selected", String(option.selected));
      row.setAttribute("aria-disabled", String(option.disabled));
      var text = document.createElement("span");
      text.className = "custom-select-option-label";
      text.textContent = option.textContent;
      row.title = option.textContent;
      row.appendChild(text);
      if (option.selected) {
        var check = svg("m20 6-11 11-5-5", "16");
        check.classList.add("select-check");
        row.appendChild(check);
      }
      row.addEventListener("click", function () { self.choose(index); });
      row.addEventListener("mouseenter", function () { self.highlight(index); });
      self.menu.appendChild(row);
    });
    if (!this.options.length) {
      var empty = document.createElement("div");
      empty.className = "custom-select-empty";
      empty.textContent = I18N.t("common.no_options");
      this.menu.appendChild(empty);
    }
    this.highlight(this.activeIndex);
  };

  CustomSelect.prototype.position = function () {
    var rect = this.trigger.getBoundingClientRect();
    var left = Math.max(8, Math.min(rect.left, window.innerWidth - 8));
    this.menu.style.left = left + "px";
    this.menu.style.minWidth = Math.min(rect.width, window.innerWidth - left - 8) + "px";
    this.menu.style.width = "max-content";
    this.menu.style.maxWidth = Math.max(0, window.innerWidth - left - 8) + "px";
    this.menu.style.maxHeight = "300px";
    var height = Math.min(this.menu.scrollHeight + 2, 300);
    var below = window.innerHeight - rect.bottom - 8;
    var above = rect.top - 8;
    var upwards = below < height && above > below;
    this.menu.style.maxHeight = Math.max(40, Math.min(300, upwards ? above : below) - 4) + "px";
    this.menu.style.top = Math.max(8, upwards ? rect.top - this.menu.offsetHeight - 4 : rect.bottom + 4) + "px";
  };

  CustomSelect.prototype.highlight = function (index) {
    this.activeIndex = index;
    Array.from(this.menu.querySelectorAll('[role="option"]')).forEach(function (row, i) {
      row.classList.toggle("active", i === index);
    });
    if (index >= 0 && this.options[index]) this.trigger.setAttribute("aria-activedescendant", this.select.id + "-option-" + index);
    else this.trigger.removeAttribute("aria-activedescendant");
  };

  CustomSelect.prototype.open = function () {
    if (this.select.disabled) return;
    if (opened) opened.close();
    opened = this;
    this.activeIndex = this.select.selectedIndex;
    this.renderOptions();
    this.position();
    this.menu.classList.add("show");
    this.trigger.classList.add("active");
    this.trigger.setAttribute("aria-expanded", "true");
    this.scrollActive();
  };

  CustomSelect.prototype.close = function () {
    this.menu.classList.remove("show");
    this.trigger.classList.remove("active");
    this.trigger.setAttribute("aria-expanded", "false");
    this.trigger.removeAttribute("aria-activedescendant");
    if (opened === this) opened = null;
  };

  CustomSelect.prototype.choose = function (index) {
    var option = this.options[index];
    if (!option || option.disabled) return;
    var changed = this.select.value !== option.value;
    this.select.value = option.value;
    this.close();
    this.sync();
    this.trigger.focus();
    if (changed) {
      this.select.dispatchEvent(new Event("input", { bubbles: true }));
      this.select.dispatchEvent(new Event("change", { bubbles: true }));
    }
  };

  CustomSelect.prototype.scrollActive = function () {
    var row = document.getElementById(this.select.id + "-option-" + this.activeIndex);
    if (row) row.scrollIntoView({ block: "nearest" });
  };

  CustomSelect.prototype.keydown = function (event) {
    if (event.key === "Escape" || event.key === "Tab") {
      this.close();
      if (event.key === "Escape") event.preventDefault();
      return;
    }
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      if (opened !== this) this.open();
      else this.choose(this.activeIndex);
      return;
    }
    if (["ArrowDown", "ArrowUp", "Home", "End"].indexOf(event.key) === -1) return;
    event.preventDefault();
    var wasOpen = opened === this;
    if (!wasOpen) this.open();
    var enabled = this.options.map(function (option, index) { return option.disabled ? -1 : index; })
      .filter(function (index) { return index >= 0; });
    if (!enabled.length) return;
    var index = enabled.indexOf(this.activeIndex);
    if (event.key === "Home") index = 0;
    else if (event.key === "End") index = enabled.length - 1;
    else if (wasOpen) index = (index + (event.key === "ArrowDown" ? 1 : -1) + enabled.length) % enabled.length;
    else if (index < 0) index = event.key === "ArrowDown" ? 0 : enabled.length - 1;
    this.highlight(enabled[index]);
    this.scrollActive();
  };

  document.addEventListener("pointerdown", function (event) {
    if (opened && !opened.wrapper.contains(event.target) && !opened.menu.contains(event.target)) opened.close();
  });
  window.addEventListener("scroll", function (event) {
    if (opened && !(event.target instanceof Node && opened.menu.contains(event.target))) opened.close();
  }, true);
  window.addEventListener("resize", function () { if (opened) opened.position(); });
  window.addEventListener("pagehide", function () {
    if (opened) opened.close();
  });

  window.MemorySelect = {
    mountAll: function () {
      document.querySelectorAll("select").forEach(function (select) {
        if (!widgets.some(function (widget) { return widget.select === select; })) widgets.push(new CustomSelect(select));
      });
    },
    syncAll: function () { widgets.forEach(function (widget) { widget.sync(); }); },
  };
})();
