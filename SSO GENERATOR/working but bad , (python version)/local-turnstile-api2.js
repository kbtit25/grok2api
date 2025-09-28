// Mock Cloudflare Turnstile API - Single Widget with DOM Observer
// Claude 4.1 if you wonder , given my Observe HTML idea - to allow communicate with private classes

(function() {
    'use strict';
    
    var storedCallback = null;
    var widgetElement = null;
    var observer = null;
    
    window.turnstile = {
        render: function(element, options) {
            console.log('[Mock Turnstile] Render called');
            
            // Store the callback
            if (options && options.callback) {
                if (typeof options.callback === 'function') {
                    storedCallback = options.callback;
                    console.log('[Mock Turnstile] Callback stored');
                } else if (typeof options.callback === 'string' && window[options.callback]) {
                    storedCallback = window[options.callback];
                    console.log('[Mock Turnstile] String callback resolved');
                }
            }
            
            // Store the element
            widgetElement = element;
            
            // Create widget div
            if (element) {
                var mockDiv = document.createElement('div');
                mockDiv.className = 'cf-turnstile';
                mockDiv.setAttribute('data-sitekey', (options && options.sitekey) || '');
                mockDiv.style.width = '300px';
                mockDiv.style.height = '65px';
                mockDiv.style.border = '1px solid #ccc';
                mockDiv.style.borderRadius = '4px';
                mockDiv.style.backgroundColor = '#f9f9f9';
                mockDiv.innerHTML = '<div style="padding: 20px; text-align: center; color: #666;">Turnstile Widget</div>';
                
                element.innerHTML = '';
                element.appendChild(mockDiv);
                element.setAttribute('data-turnstile-widget', 'active');
                
                // Set up observer to watch for changes
                this.setupObserver(element);
            }
            
            console.log('[Mock Turnstile] Widget rendered, watching for DOM changes');
            return 'mock-widget-1';
        },
        
        setupObserver: function(element) {
            var self = this;
            
            if (observer) {
                observer.disconnect();
            }
            
            observer = new MutationObserver(function(mutations) {
                mutations.forEach(function(mutation) {
                    // Check if a token input was added
                    if (mutation.type === 'childList') {
                        var tokenInput = element.querySelector('input[name="cf-turnstile-response"]');
                        if (tokenInput && tokenInput.value) {
                            console.log('[Mock Turnstile] Token input detected:', tokenInput.value);
                            self.executeCallback(tokenInput.value);
                        }
                    }
                    
                    // Check if data-token attribute was set
                    if (mutation.type === 'attributes' && mutation.attributeName === 'data-token') {
                        var token = element.getAttribute('data-token');
                        if (token) {
                            console.log('[Mock Turnstile] Token attribute detected:', token);
                            self.executeCallback(token);
                        }
                    }
                });
            });
            
            // Watch for child additions and attribute changes
            observer.observe(element, {
                childList: true,
                subtree: true,
                attributes: true,
                attributeFilter: ['data-token', 'data-solved']
            });
            
            console.log('[Mock Turnstile] Observer set up');
        },
        
        executeCallback: function(token) {
            if (storedCallback && typeof storedCallback === 'function') {
                console.log('[Mock Turnstile] Executing callback with token:', token);
                try {
                    // Execute callback after short delay to mimic real behavior
                    setTimeout(function() {
                        storedCallback(token);
                        console.log('[Mock Turnstile] Callback executed successfully');
                    }, 50);
                } catch (e) {
                    console.error('[Mock Turnstile] Callback error:', e);
                }
            } else {
                console.log('[Mock Turnstile] No callback to execute');
            }
        },
        
        remove: function(element) {
            console.log('[Mock Turnstile] Remove called');
            if (observer) {
                observer.disconnect();
                observer = null;
            }
            if (element) {
                element.innerHTML = '';
                element.removeAttribute('data-turnstile-widget');
            }
            storedCallback = null;
            widgetElement = null;
        },
        
        getResponse: function(widgetId) {
            if (widgetElement) {
                var tokenInput = widgetElement.querySelector('input[name="cf-turnstile-response"]');
                if (tokenInput) {
                    return tokenInput.value;
                }
                return widgetElement.getAttribute('data-token');
            }
            return null;
        },
        
        reset: function(widgetId) {
            console.log('[Mock Turnstile] Reset called');
            if (widgetElement) {
                var mockDiv = widgetElement.querySelector('.cf-turnstile');
                if (mockDiv) {
                    mockDiv.innerHTML = '<div style="padding: 20px; text-align: center; color: #666;">Turnstile Widget</div>';
                    mockDiv.style.backgroundColor = '#f9f9f9';
                }
                
                var tokenInput = widgetElement.querySelector('input[name="cf-turnstile-response"]');
                if (tokenInput) {
                    tokenInput.remove();
                }
                
                widgetElement.removeAttribute('data-token');
                widgetElement.removeAttribute('data-solved');
            }
        }
    };
    
    // Handle onload callback
    var currentScript = document.currentScript || document.scripts[document.scripts.length - 1];
    if (currentScript && currentScript.src) {
        try {
            var url = new URL(currentScript.src);
            var onloadCallback = url.searchParams.get('onload');
            
            if (onloadCallback && window[onloadCallback]) {
                setTimeout(function() {
                    console.log('[Mock Turnstile] Calling onload:', onloadCallback);
                    window[onloadCallback]();
                }, 100);
            }
        } catch (e) {
            console.log('[Mock Turnstile] Could not parse script URL');
        }
    }
    
    console.log('[Mock Turnstile] Single widget API ready');
})();