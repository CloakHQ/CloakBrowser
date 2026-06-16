// PX DOM 探测器 —— 全面扫描页面判断 PX 挑战状态
(function() {
  var result = {
    url: window.location.href,
    diagnosis: 'unknown',
    modalVisible: false,
    onIfoodApp: false,
    isCf: false,
    isBlockPage: false,
    pxGlobals: [],
    shadowHosts: [],
    main: { title: document.title, markersFound: [], bodyPreview: '' },
  };

  // 检测 Cloudflare 阻断页
  var cfId = document.getElementById('cf-please-wait');
  if (cfId || document.querySelector('.cf-browser-verification')) {
    result.isCf = true;
    result.diagnosis = 'cf_challenge';
  }

  // 检测整页 PX 阻断（body 只有简短验证信息）
  var bodyText = (document.body ? document.body.innerText : '') || '';
  result.main.bodyPreview = bodyText.slice(0, 300);
  var markers = ['activate and hold', 'press and hold', 'pressione e segure',
    'antes de continuarmos', 'confirmar que você', 'robot or human',
    'px-captcha'];
  for (var i = 0; i < markers.length; i++) {
    if (bodyText.toLowerCase().includes(markers[i])) {
      result.main.markersFound.push(markers[i]);
    }
  }
  // 如果 body 文本很短且包含验证关键词，可能是整页阻断
  if (bodyText.length < 500 && result.main.markersFound.length > 0) {
    result.isBlockPage = true;
    result.diagnosis = 'px_block_page';
  }

  // 检测 PX 弹层 / 容器
  var modal = document.getElementById('px-captcha-modal');
  if (modal) {
    var mr = modal.getBoundingClientRect();
    if (mr.width > 10 && mr.height > 10) {
      result.modalVisible = true;
      result.diagnosis = 'px_modal';
    }
  }
  var captcha = document.getElementById('px-captcha');
  if (captcha) {
    var cr = captcha.getBoundingClientRect();
    if (cr.width > 10 && cr.height > 10) {
      result.modalVisible = true;
      result.diagnosis = 'px_captcha';
    }
  }
  var pxEl = document.querySelector('[data-px-captcha], .px-challenge');
  if (pxEl) {
    var pr = pxEl.getBoundingClientRect();
    if (pr.width > 10 && pr.height > 10) {
      result.modalVisible = true;
      result.diagnosis = 'px_element';
    }
  }

  // 检测 Shadow DOM 中的 PX
  try {
    document.querySelectorAll('*').forEach(function(el) {
      if (el.shadowRoot) {
        var sr = el.shadowRoot;
        if (sr.getElementById('px-captcha') || sr.getElementById('px-captcha-modal')
            || sr.querySelector('[data-px-captcha]')) {
          result.shadowHosts.push(el.tagName);
          result.modalVisible = true;
          result.diagnosis = 'px_shadow';
        }
      }
    });
  } catch(e) {}

  // 检测 PX 全局变量
  var pxKeys = ['_pxApp', '_pxUuid', '_pxCss', '_pxCaptcha', '_px', 'PerimeterX'];
  for (var j = 0; j < pxKeys.length; j++) {
    if (window[pxKeys[j]] !== undefined) result.pxGlobals.push(pxKeys[j]);
  }

  // 检测 iFood webpack app
  result.onIfoodApp = typeof window.__NEXT_DATA__ !== 'undefined'
    || (window.webpackChunk_N_E && window.webpackChunk_N_E.length > 0);

  return result;
})();