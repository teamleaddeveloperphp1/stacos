(function () {
  'use strict';

  // Mirrors backend/apps/itr/validators.py -- keep these regexes in sync
  // with PAN_REGEX / MOBILE_REGEX there if either changes.
  var PAN_REGEX = /^[A-Z]{5}[0-9]{4}[A-Z]{1}$/;
  var MOBILE_REGEX = /^[0-9]{10}$/;
  var EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

  var REQUIRED_FIELDS = ['pan', 'dob', 'email', 'first_name', 'last_name', 'gender', 'father_name', 'mobile_number'];

  function validatorFor(fieldName) {
    switch (fieldName) {
      case 'pan':
        return function (value) {
          var v = value.trim().toUpperCase();
          if (!v) return 'PAN is required.';
          if (!PAN_REGEX.test(v)) return 'Enter a valid PAN.';
          return '';
        };
      case 'mobile_number':
        return function (value) {
          var v = value.trim();
          if (!v) return 'Mobile Number is required.';
          if (!MOBILE_REGEX.test(v)) return 'Enter a valid 10-digit mobile number.';
          return '';
        };
      case 'email':
        return function (value) {
          var v = value.trim();
          if (!v) return 'Email is required.';
          if (!EMAIL_REGEX.test(v)) return 'Enter a valid email address.';
          return '';
        };
      default:
        return function (value) {
          if (!value || !value.trim()) return 'This field is required.';
          return '';
        };
    }
  }

  function errorContainerFor(field) {
    // Reuse Django's own {{ form.<field>.errors }} <ul class="errorlist">
    // if the field already has one server-rendered, instead of duplicating it.
    var next = field.nextElementSibling;
    if (next && next.classList.contains('errorlist')) {
      return next;
    }
    var container = document.createElement('ul');
    container.className = 'errorlist js-field-error';
    field.parentNode.insertBefore(container, field.nextSibling);
    return container;
  }

  function showError(field, message) {
    var container = errorContainerFor(field);
    container.innerHTML = message ? '<li>' + message + '</li>' : '';
  }

  function attach(form) {
    var fields = REQUIRED_FIELDS
      .map(function (name) { return form.querySelector('[name="' + name + '"]'); })
      .filter(Boolean);

    fields.forEach(function (field) {
      var validate = validatorFor(field.name);
      field.addEventListener('blur', function () {
        showError(field, validate(field.value || ''));
      });
      // Once an error is showing, re-check on every keystroke so it clears
      // as soon as the user fixes it, instead of waiting for the next blur.
      field.addEventListener('input', function () {
        var container = field.nextElementSibling;
        if (container && container.classList.contains('js-field-error') && container.innerHTML) {
          showError(field, validate(field.value || ''));
        }
      });
    });

    form.addEventListener('submit', function (event) {
      var firstInvalid = null;
      fields.forEach(function (field) {
        var validate = validatorFor(field.name);
        var message = validate(field.value || '');
        showError(field, message);
        if (message && !firstInvalid) firstInvalid = field;
      });
      if (firstInvalid) {
        event.preventDefault();
        firstInvalid.focus();
      }
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    var form = document.querySelector('.dashboard form');
    if (form) attach(form);
  });
})();
