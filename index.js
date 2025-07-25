import express from 'express';
import fetch from 'node-fetch';
import FormData from 'form-data';
import dotenv from 'dotenv';
import cors from 'cors';
import puppeteer from 'puppeteer-extra'
import StealthPlugin from 'puppeteer-extra-plugin-stealth'
import { v4 as uuidv4 } from 'uuid';
import Logger from './logger.js';

dotenv.config();

// 配置常量
const CONFIG = {
    MODELS: {
        'grok-2': 'grok-latest',
        'grok-2-imageGen': 'grok-latest',
        'grok-2-search': 'grok-latest',
        "grok-3": "grok-3",
        "grok-3-search": "grok-3",
        "grok-3-imageGen": "grok-3",
        "grok-3-deepsearch": "grok-3",
        "grok-3-reasoning": "grok-3"
    },
    API: {
        IS_TEMP_CONVERSATION: process.env.IS_TEMP_CONVERSATION == undefined ? false : process.env.IS_TEMP_CONVERSATION == 'true',
        IS_TEMP_GROK2: process.env.IS_TEMP_GROK2 == undefined ? true : process.env.IS_TEMP_GROK2 == 'true',
        GROK2_CONCURRENCY_LEVEL: process.env.GROK2_CONCURRENCY_LEVEL || 4,
        IS_CUSTOM_SSO: process.env.IS_CUSTOM_SSO == undefined ? false : process.env.IS_CUSTOM_SSO == 'true',
        BASE_URL: "https://grok.com",
        API_KEY: process.env.API_KEY || "sk-123456",
        SIGNATURE_COOKIE: null,
        TEMP_COOKIE: null,
        PICGO_KEY: process.env.PICGO_KEY || null, //想要流式生图的话需要填入这个PICGO图床的key
        TUMY_KEY: process.env.TUMY_KEY || null //想要流式生图的话需要填入这个TUMY图床的key 两个图床二选一，默认使用PICGO
    },
    SERVER: {
        PORT: process.env.PORT || 3000,
        BODY_LIMIT: '5mb'
    },
    RETRY: {
        MAX_ATTEMPTS: 2//重试次数
    },
    SHOW_THINKING: process.env.SHOW_THINKING == undefined ? true : process.env.SHOW_THINKING == 'true',
    IS_THINKING: false,
    IS_IMG_GEN: false,
    IS_IMG_GEN2: false,
    TEMP_COOKIE_INDEX: 0,//临时cookie的下标
    ISSHOW_SEARCH_RESULTS: process.env.ISSHOW_SEARCH_RESULTS == undefined ? true : process.env.ISSHOW_SEARCH_RESULTS == 'true',//是否显示搜索结果
    CHROME_PATH: process.env.CHROME_PATH || null
};
puppeteer.use(StealthPlugin())

// 请求头配置
const DEFAULT_HEADERS = {
    'accept': '*/*',
    'accept-language': 'zh-CN,zh;q=0.9',
    'accept-encoding': 'gzip, deflate, br, zstd',
    'content-type': 'text/plain;charset=UTF-8',
    'Connection': 'keep-alive',
    'origin': 'https://grok.com',
    'priority': 'u=1, i',
    'sec-ch-ua': '"Chromium";v="130", "Google Chrome";v="130", "Not?A_Brand";v="99"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"Windows"',
    'sec-fetch-dest': 'empty',
    'sec-fetch-mode': 'cors',
    'sec-fetch-site': 'same-origin',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36',
    'baggage': 'sentry-public_key=b311e0f2690c81f25e2c4cf6d4f7ce1c'
};


async function initialization() {
    if (CONFIG.CHROME_PATH == null) {
        try {
            CONFIG.CHROME_PATH = puppeteer.executablePath();
        } catch (error) {
            CONFIG.CHROME_PATH = "/usr/bin/chromium";
        }
    }
    Logger.info(`CHROME_PATH: ${CONFIG.CHROME_PATH}`, 'Server');
    if (CONFIG.API.IS_CUSTOM_SSO) {
        if (CONFIG.API.IS_TEMP_GROK2) {
            await tempCookieManager.ensureCookies();
        }
        return;
    }
    const ssoArray = process.env.SSO.split(',');
    const concurrencyLimit = 3;
    for (let i = 0; i < ssoArray.length; i += concurrencyLimit) {
        const batch = ssoArray.slice(i, i + concurrencyLimit);
        const batchPromises = batch.map(sso =>
            tokenManager.addToken(`sso-rw=${sso};sso=${sso}`)
        );

        await Promise.all(batchPromises);
        Logger.info(`已加载令牌: ${i} 个`, 'Server');
        await new Promise(resolve => setTimeout(resolve, 1000));
    }
    Logger.info(`令牌加载完成: ${JSON.stringify(tokenManager.getAllTokens(), null, 2)}`, 'Server');
    Logger.info(`共加载: ${tokenManager.getAllTokens().length}个令牌`, 'Server');
    if (CONFIG.API.IS_TEMP_GROK2) {
        await tempCookieManager.ensureCookies();
        CONFIG.API.TEMP_COOKIE = tempCookieManager.cookies[tempCookieManager.currentIndex];
    }
    Logger.info("初始化完成", 'Server');
}

class AuthTokenManager {
    constructor() {
        this.tokenModelMap = {};
        this.expiredTokens = new Set();
        this.tokenStatusMap = {};

        // 定义模型请求频率限制和过期时间
        this.modelConfig = {
            "grok-2": {
                RequestFrequency: 30,
                ExpirationTime: 1 * 60 * 60 * 1000 // 1小时
            },
            "grok-3": {
                RequestFrequency: 100,
                ExpirationTime: 2 * 60 * 60 * 1000 // 2小时
            },
            "grok-3-deepsearch": {
                RequestFrequency: 30,
                ExpirationTime: 24 * 60 * 60 * 1000 // 24小时
            },
            "grok-3-reasoning": {
                RequestFrequency: 30,
                ExpirationTime: 24 * 60 * 60 * 1000 // 24小时
            }
        };
        this.tokenResetSwitch = false;
        this.tokenResetTimer = null;
    }
    async fetchGrokStats(token, modelName) {
        let requestKind = 'DEFAULT';
        if (modelName == 'grok-2' || modelName == 'grok-3') {
            requestKind = 'DEFAULT';
        } else if (modelName == 'grok-3-deepsearch') {
            requestKind = 'DEEPSEARCH';
        } else if (modelName == 'grok-3-reasoning') {
            requestKind = 'REASONING';
        }
        const response = await fetch('https://grok.com/rest/rate-limits', {
            method: 'POST',
            headers: {
                'content-type': 'application/json',
                'Cookie': token,
            },
            body: JSON.stringify({
                "requestKind": requestKind,
                "modelName": modelName == 'grok-2' ? 'grok-latest' : "grok-3"
            })
        });

        if (response.status != 200) {
            return 0;
        }
        const data = await response.json();
        return data.remainingQueries;
    }
    async addToken(token) {
        const sso = token.split("sso=")[1].split(";")[0];

        for (const model of Object.keys(this.modelConfig)) {
            if (!this.tokenModelMap[model]) {
                this.tokenModelMap[model] = [];
            }
            if (!this.tokenStatusMap[sso]) {
                this.tokenStatusMap[sso] = {};
            }
            const existingTokenEntry = this.tokenModelMap[model].find(entry => entry.token === token);

            if (!existingTokenEntry) {
                try {
                    const remainingQueries = await this.fetchGrokStats(token, model);

                    const modelRequestFrequency = this.modelConfig[model].RequestFrequency;
                    const usedRequestCount = modelRequestFrequency - remainingQueries;

                    if (usedRequestCount === modelRequestFrequency) {
                        this.expiredTokens.add({
                            token: token,
                            model: model,
                            expiredTime: Date.now()
                        });

                        if (!this.tokenStatusMap[sso][model]) {
                            this.tokenStatusMap[sso][model] = {
                                isValid: false,
                                invalidatedTime: Date.now(),
                                totalRequestCount: Math.max(0, usedRequestCount)
                            };
                        }

                        if (!this.tokenResetSwitch) {
                            this.startTokenResetProcess();
                            this.tokenResetSwitch = true;
                        }
                    } else {
                        this.tokenModelMap[model].push({
                            token: token,
                            RequestCount: Math.max(0, usedRequestCount),
                            AddedTime: Date.now(),
                            StartCallTime: null
                        });

                        if (!this.tokenStatusMap[sso][model]) {
                            this.tokenStatusMap[sso][model] = {
                                isValid: true,
                                invalidatedTime: null,
                                totalRequestCount: Math.max(0, usedRequestCount)
                            };
                        }
                    }
                } catch (error) {
                    this.tokenModelMap[model].push({
                        token: token,
                        RequestCount: 0,
                        AddedTime: Date.now(),
                        StartCallTime: null
                    });

                    if (!this.tokenStatusMap[sso][model]) {
                        this.tokenStatusMap[sso][model] = {
                            isValid: true,
                            invalidatedTime: null,
                            totalRequestCount: 0
                        };
                    }

                    Logger.error(`获取模型 ${model} 的统计信息失败: ${error}`, 'TokenManager');
                }
                await Utils.delay(200);
            }
        }
    }

    setToken(token) {
        const models = Object.keys(this.modelConfig);
        this.tokenModelMap = models.reduce((map, model) => {
            map[model] = [{
                token,
                RequestCount: 0,
                AddedTime: Date.now(),
                StartCallTime: null
            }];
            return map;
        }, {});
        const sso = token.split("sso=")[1].split(";")[0];
        this.tokenStatusMap[sso] = models.reduce((statusMap, model) => {
            statusMap[model] = {
                isValid: true,
                invalidatedTime: null,
                totalRequestCount: 0
            };
            return statusMap;
        }, {});
    }

    async deleteToken(token) {
        try {
            const sso = token.split("sso=")[1].split(";")[0];
            await Promise.all([
                new Promise((resolve) => {
                    this.tokenModelMap = Object.fromEntries(
                        Object.entries(this.tokenModelMap).map(([model, entries]) => [
                            model,
                            entries.filter(entry => entry.token !== token)
                        ])
                    );
                    resolve();
                }),

                new Promise((resolve) => {
                    delete this.tokenStatusMap[sso];
                    resolve();
                }),
            ]);
            Logger.info(`令牌已成功移除: ${token}`, 'TokenManager');
            return true;
        } catch (error) {
            Logger.error('令牌删除失败：', error);
            return false;
        }
    }
    getNextTokenForModel(modelId) {
        const normalizedModel = this.normalizeModelName(modelId);

        if (!this.tokenModelMap[normalizedModel] || this.tokenModelMap[normalizedModel].length === 0) {
            return null;
        }
        const tokenEntry = this.tokenModelMap[normalizedModel][0];

        if (tokenEntry) {
            if (tokenEntry.StartCallTime === null || tokenEntry.StartCallTime === undefined) {
                tokenEntry.StartCallTime = Date.now();
            }
            if (!this.tokenResetSwitch) {
                this.startTokenResetProcess();
                this.tokenResetSwitch = true;
            }
            tokenEntry.RequestCount++;

            if (tokenEntry.RequestCount > this.modelConfig[normalizedModel].RequestFrequency) {
                this.removeTokenFromModel(normalizedModel, tokenEntry.token);
                const nextTokenEntry = this.tokenModelMap[normalizedModel][0];
                return nextTokenEntry ? nextTokenEntry.token : null;
            }
            const sso = tokenEntry.token.split("sso=")[1].split(";")[0];
            if (this.tokenStatusMap[sso] && this.tokenStatusMap[sso][normalizedModel]) {
                if (tokenEntry.RequestCount === this.modelConfig[normalizedModel].RequestFrequency) {
                    this.tokenStatusMap[sso][normalizedModel].isValid = false;
                    this.tokenStatusMap[sso][normalizedModel].invalidatedTime = Date.now();
                }
                this.tokenStatusMap[sso][normalizedModel].totalRequestCount++;
            }
            return tokenEntry.token;
        }

        return null;
    }

    removeTokenFromModel(modelId, token) {
        const normalizedModel = this.normalizeModelName(modelId);

        if (!this.tokenModelMap[normalizedModel]) {
            Logger.error(`模型 ${normalizedModel} 不存在`, 'TokenManager');
            return false;
        }

        const modelTokens = this.tokenModelMap[normalizedModel];
        const tokenIndex = modelTokens.findIndex(entry => entry.token === token);

        if (tokenIndex !== -1) {
            const removedTokenEntry = modelTokens.splice(tokenIndex, 1)[0];
            this.expiredTokens.add({
                token: removedTokenEntry.token,
                model: normalizedModel,
                expiredTime: Date.now()
            });

            if (!this.tokenResetSwitch) {
                this.startTokenResetProcess();
                this.tokenResetSwitch = true;
            }
            Logger.info(`模型${modelId}的令牌已失效，已成功移除令牌: ${token}`, 'TokenManager');
            return true;
        }

        Logger.error(`在模型 ${normalizedModel} 中未找到 token: ${token}`, 'TokenManager');
        return false;
    }

    getExpiredTokens() {
        return Array.from(this.expiredTokens);
    }

    normalizeModelName(model) {
        if (model.startsWith('grok-') && !model.includes('deepsearch') && !model.includes('reasoning')) {
            return model.split('-').slice(0, 2).join('-');
        }
        return model;
    }

    getTokenCountForModel(modelId) {
        const normalizedModel = this.normalizeModelName(modelId);
        return this.tokenModelMap[normalizedModel]?.length || 0;
    }

    getRemainingTokenRequestCapacity() {
        const remainingCapacityMap = {};

        Object.keys(this.modelConfig).forEach(model => {
            const modelTokens = this.tokenModelMap[model] || [];

            const modelRequestFrequency = this.modelConfig[model].RequestFrequency;

            const totalUsedRequests = modelTokens.reduce((sum, tokenEntry) => {
                return sum + (tokenEntry.RequestCount || 0);
            }, 0);

            // 计算剩余可用请求数量
            const remainingCapacity = (modelTokens.length * modelRequestFrequency) - totalUsedRequests;
            remainingCapacityMap[model] = Math.max(0, remainingCapacity);
        });

        return remainingCapacityMap;
    }

    getTokenArrayForModel(modelId) {
        const normalizedModel = this.normalizeModelName(modelId);
        return this.tokenModelMap[normalizedModel] || [];
    }

    startTokenResetProcess() {
        if (this.tokenResetTimer) {
            clearInterval(this.tokenResetTimer);
        }

        this.tokenResetTimer = setInterval(() => {
            const now = Date.now();

            this.expiredTokens.forEach(expiredTokenInfo => {
                const { token, model, expiredTime } = expiredTokenInfo;
                const expirationTime = this.modelConfig[model].ExpirationTime;
                if (now - expiredTime >= expirationTime) {
                    if (!this.tokenModelMap[model].some(entry => entry.token === token)) {
                        this.tokenModelMap[model].push({
                            token: token,
                            RequestCount: 0,
                            AddedTime: now,
                            StartCallTime: null
                        });
                    }
                    const sso = token.split("sso=")[1].split(";")[0];

                    if (this.tokenStatusMap[sso] && this.tokenStatusMap[sso][model]) {
                        this.tokenStatusMap[sso][model].isValid = true;
                        this.tokenStatusMap[sso][model].invalidatedTime = null;
                        this.tokenStatusMap[sso][model].totalRequestCount = 0;
                    }

                    this.expiredTokens.delete(expiredTokenInfo);
                }
            });

            Object.keys(this.modelConfig).forEach(model => {
                if (!this.tokenModelMap[model]) return;
    
                const processedTokens = this.tokenModelMap[model].map(tokenEntry => {
                    if (!tokenEntry.StartCallTime) return tokenEntry;
    
                    const expirationTime = this.modelConfig[model].ExpirationTime;
                    if (now - tokenEntry.StartCallTime >= expirationTime) {
                        const sso = tokenEntry.token.split("sso=")[1].split(";")[0];
                        if (this.tokenStatusMap[sso] && this.tokenStatusMap[sso][model]) {
                            this.tokenStatusMap[sso][model].isValid = true;
                            this.tokenStatusMap[sso][model].invalidatedTime = null;
                            this.tokenStatusMap[sso][model].totalRequestCount = 0;
                        }
                        
                        return {
                            ...tokenEntry,
                            RequestCount: 0,
                            StartCallTime: null
                        };
                    }
                    
                    return tokenEntry;
                });
    
                this.tokenModelMap[model] = processedTokens;
            });
        }, 1 * 60 * 60 * 1000); 
    }

    getAllTokens() {
        const allTokens = new Set();
        Object.values(this.tokenModelMap).forEach(modelTokens => {
            modelTokens.forEach(entry => allTokens.add(entry.token));
        });
        return Array.from(allTokens);
    }

    getTokenStatusMap() {
        return this.tokenStatusMap;
    }
}


class Utils {
    static delay(time) {
        return new Promise(function (resolve) {
            setTimeout(resolve, time)
        });
    }
    static async organizeSearchResults(searchResults) {
        // 确保传入的是有效的搜索结果对象
        if (!searchResults || !searchResults.results) {
            return '';
        }

        const results = searchResults.results;
        const formattedResults = results.map((result, index) => {
            // 处理可能为空的字段
            const title = result.title || '未知标题';
            const url = result.url || '#';
            const preview = result.preview || '无预览内容';

            return `\r\n<details><summary>资料[${index}]: ${title}</summary>\r\n${preview}\r\n\n[Link](${url})\r\n</details>`;
        });
        return formattedResults.join('\n\n');
    }
    static async createAuthHeaders(model) {
        return await tokenManager.getNextTokenForModel(model);
    }
}
class GrokTempCookieManager {
    constructor() {
        this.cookies = [];
        this.currentIndex = 0;
        this.isRefreshing = false;
        this.initialCookieCount = CONFIG.API.GROK2_CONCURRENCY_LEVEL;
        this.extractCount = 0;
    }

    async ensureCookies() {
        // 如果 cookies 数量不足，则重新获取
        if (this.cookies.length < this.initialCookieCount) {
            await this.refreshCookies();
        }
    }
    async extractGrokHeaders(browser) {
        Logger.info("开始提取头信息", 'Server');
        try {
            const page = await browser.newPage();
            await page.goto('https://grok.com/', { waitUntil: 'domcontentloaded' });
            let waitTime = 0;
            const targetHeaders = ['x-anonuserid', 'x-challenge', 'x-signature'];

            while (true) {
                const cookies = await page.cookies();
                const extractedHeaders = cookies
                    .filter(cookie => targetHeaders.includes(cookie.name.toLowerCase()))
                    .map(cookie => `${cookie.name}=${cookie.value}`);

                if (targetHeaders.every(header =>
                    extractedHeaders.some(cookie => cookie && cookie.startsWith(header + '='))
                )) {
                    await browser.close();
                    Logger.info('提取的头信息:', JSON.stringify(extractedHeaders, null, 2), 'Server');
                    this.cookies.push(extractedHeaders.join(';'));
                    this.extractCount++;
                    return true;
                }

                await Utils.delay(500);
                waitTime += 500;
                if (waitTime >= 10000) {
                    await browser.close();
                    return null;
                }
            }
        } catch (error) {
            Logger.error('获取头信息出错:', error, 'Server');
            return null;
        }
    }
    async initializeTempCookies(count = 1) {
        Logger.info(`开始初始化 ${count} 个临时账号认证信息`, 'Server');
        const browserOptions = {
            headless: true,
            args: [
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-gpu'
            ],
            executablePath: CONFIG.CHROME_PATH
        };

        const browsers = await Promise.all(
            Array.from({ length: count }, () => puppeteer.launch(browserOptions))
        );

        const cookiePromises = browsers.map(browser => this.extractGrokHeaders(browser));
        return Promise.all(cookiePromises);
    }
    async refreshCookies() {
        if (this.isRefreshing) return;
        this.isRefreshing = true;
        this.extractCount = 0;
        try {
            // 获取新的 cookies
            let retryCount = 0;
            let remainingCount = this.initialCookieCount - this.cookies.length;

            while (retryCount < CONFIG.RETRY.MAX_ATTEMPTS) {
                await this.initializeTempCookies(remainingCount);
                if (this.extractCount != remainingCount) {
                    if (this.extractCount == 0) {
                        Logger.error(`无法获取足够的有效 TempCookies，可能网络存在问题，当前数量：${this.cookies.length}`);
                    } else if (this.extractCount < remainingCount) {
                        remainingCount -= this.extractCount;
                        this.extractCount = 0;
                        retryCount++;
                        await Utils.delay(1000 * retryCount);
                    } else {
                        break;
                    }
                } else {
                    break;
                }
            }
            if (this.currentIndex >= this.cookies.length) {
                this.currentIndex = 0;
            }

            if (this.cookies.length < this.initialCookieCount) {
                if (this.cookies.length !== 0) {
                    // 如果已经获取到一些 TempCookies，则只提示警告错误
                    Logger.error(`无法获取足够的有效 TempCookies，可能网络存在问题，当前数量：${this.cookies.length}`);
                } else {
                    // 如果未获取到任何 TempCookies，则抛出错误
                    throw new Error(`无法获取足够的有效 TempCookies，可能网络存在问题，当前数量：${this.cookies.length}`);
                }
            }
        } catch (error) {
            Logger.error('刷新 cookies 失败:', error);
        } finally {
            Logger.info(`已提取${this.cookies.length}个TempCookies`, 'Server');
            Logger.info(`提取的TempCookies为${JSON.stringify(this.cookies, null, 2)}`, 'Server');
            this.isRefreshing = false;
        }
    }
}

class GrokApiClient {
    constructor(modelId) {
        if (!CONFIG.MODELS[modelId]) {
            throw new Error(`不支持的模型: ${modelId}`);
        }
        this.modelId = CONFIG.MODELS[modelId];
    }

    processMessageContent(content) {
        if (typeof content === 'string') return content;
        return null;
    }
    // 获取图片类型
    getImageType(base64String) {
        let mimeType = 'image/jpeg';
        if (base64String.includes('data:image')) {
            const matches = base64String.match(/data:([a-zA-Z0-9]+\/[a-zA-Z0-9-.+]+);base64,/);
            if (matches) {
                mimeType = matches[1];
            }
        }
        const extension = mimeType.split('/')[1];
        const fileName = `image.${extension}`;

        return {
            mimeType: mimeType,
            fileName: fileName
        };
    }

    async uploadBase64Image(base64Data, url) {
        try {
            // 处理 base64 数据
            let imageBuffer;
            if (base64Data.includes('data:image')) {
                imageBuffer = base64Data.split(',')[1];
            } else {
                imageBuffer = base64Data
            }
            const { mimeType, fileName } = this.getImageType(base64Data);
            let uploadData = {
                rpc: "uploadFile",
                req: {
                    fileName: fileName,
                    fileMimeType: mimeType,
                    content: imageBuffer
                }
            };
            Logger.info("发送图片请求", 'Server');
            // 发送请求
            const response = await fetch(url, {
                method: 'POST',
                headers: {
                    ...CONFIG.DEFAULT_HEADERS,
                    "cookie": CONFIG.API.SIGNATURE_COOKIE
                },
                body: JSON.stringify(uploadData)
            });

            if (!response.ok) {
                Logger.error(`上传图片失败,状态码:${response.status},原因:${response.error}`, 'Server');
                return '';
            }

            const result = await response.json();
            Logger.info('上传图片成功:', result, 'Server');
            return result.fileMetadataId;

        } catch (error) {
            Logger.error(error, 'Server');
            return '';
        }
    }

    async prepareChatRequest(request) {
        if ((request.model === 'grok-2-imageGen' || request.model === 'grok-3-imageGen') && !CONFIG.API.PICGO_KEY && !CONFIG.API.TUMY_KEY && request.stream) {
            throw new Error(`该模型流式输出需要配置PICGO或者TUMY图床密钥!`);
        }

        // 处理画图模型的消息限制
        let todoMessages = request.messages;
        if (request.model === 'grok-2-imageGen' || request.model === 'grok-3-imageGen') {
            const lastMessage = todoMessages[todoMessages.length - 1];
            if (lastMessage.role !== 'user') {
                throw new Error('画图模型的最后一条消息必须是用户消息!');
            }
            todoMessages = [lastMessage];
        }

        const fileAttachments = [];
        let messages = '';
        let lastRole = null;
        let lastContent = '';
        const search = request.model === 'grok-2-search' || request.model === 'grok-3-search';

        // 移除<think>标签及其内容和base64图片
        const removeThinkTags = (text) => {
            text = text.replace(/<think>[\s\S]*?<\/think>/g, '').trim();
            text = text.replace(/!\[image\]\(data:.*?base64,.*?\)/g, '[图片]');
            return text;
        };

        const processImageUrl = async (content) => {
            if (content.type === 'image_url' && content.image_url.url.includes('data:image')) {
                const imageResponse = await this.uploadBase64Image(
                    content.image_url.url,
                    `${CONFIG.API.BASE_URL}/api/rpc`
                );
                return imageResponse;
            }
            return null;
        };

        const processContent = async (content) => {
            if (Array.isArray(content)) {
                let textContent = '';
                for (const item of content) {
                    if (item.type === 'image_url') {
                        textContent += (textContent ? '\n' : '') + "[图片]";
                    } else if (item.type === 'text') {
                        textContent += (textContent ? '\n' : '') + removeThinkTags(item.text);
                    }
                }
                return textContent;
            } else if (typeof content === 'object' && content !== null) {
                if (content.type === 'image_url') {
                    return "[图片]";
                } else if (content.type === 'text') {
                    return removeThinkTags(content.text);
                }
            }
            return removeThinkTags(this.processMessageContent(content));
        };

        for (const current of todoMessages) {
            const role = current.role === 'assistant' ? 'assistant' : 'user';
            const isLastMessage = current === todoMessages[todoMessages.length - 1];

            // 处理图片附件
            if (isLastMessage && current.content) {
                if (Array.isArray(current.content)) {
                    for (const item of current.content) {
                        if (item.type === 'image_url') {
                            const processedImage = await processImageUrl(item);
                            if (processedImage) fileAttachments.push(processedImage);
                        }
                    }
                } else if (current.content.type === 'image_url') {
                    const processedImage = await processImageUrl(current.content);
                    if (processedImage) fileAttachments.push(processedImage);
                }
            }

            // 处理文本内容
            const textContent = await processContent(current.content);

            if (textContent || (isLastMessage && fileAttachments.length > 0)) {
                if (role === lastRole && textContent) {
                    lastContent += '\n' + textContent;
                    messages = messages.substring(0, messages.lastIndexOf(`${role.toUpperCase()}: `)) +
                        `${role.toUpperCase()}: ${lastContent}\n`;
                } else {
                    messages += `${role.toUpperCase()}: ${textContent || '[图片]'}\n`;
                    lastContent = textContent;
                    lastRole = role;
                }
            }
        }

        return {
            temporary: CONFIG.API.IS_TEMP_CONVERSATION,
            modelName: this.modelId,
            message: messages.trim(),
            fileAttachments: fileAttachments.slice(0, 4),
            imageAttachments: [],
            disableSearch: false,
            enableImageGeneration: true,
            returnImageBytes: false,
            returnRawGrokInXaiRequest: false,
            enableImageStreaming: false,
            imageGenerationCount: 1,
            forceConcise: false,
            toolOverrides: {
                imageGen: request.model === 'grok-2-imageGen' || request.model === 'grok-3-imageGen',
                webSearch: search,
                xSearch: search,
                xMediaSearch: search,
                trendsSearch: search,
                xPostAnalyze: search
            },
            enableSideBySide: true,
            isPreset: false,
            sendFinalMetadata: true,
            customInstructions: "",
            deepsearchPreset: request.model === 'grok-3-deepsearch' ? "default" : "",
            isReasoning: request.model === 'grok-3-reasoning'
        };
    }
}

class MessageProcessor {
    static createChatResponse(message, model, isStream = false) {
        const baseResponse = {
            id: `chatcmpl-${uuidv4()}`,
            created: Math.floor(Date.now() / 1000),
            model: model
        };

        if (isStream) {
            return {
                ...baseResponse,
                object: 'chat.completion.chunk',
                choices: [{
                    index: 0,
                    delta: {
                        content: message
                    }
                }]
            };
        }

        return {
            ...baseResponse,
            object: 'chat.completion',
            choices: [{
                index: 0,
                message: {
                    role: 'assistant',
                    content: message
                },
                finish_reason: 'stop'
            }],
            usage: null
        };
    }
}
async function processModelResponse(response, model) {
    let result = { token: null, imageUrl: null }
    if (CONFIG.IS_IMG_GEN) {
        if (response?.cachedImageGenerationResponse && !CONFIG.IS_IMG_GEN2) {
            result.imageUrl = response.cachedImageGenerationResponse.imageUrl;
        }
        return result;
    }

    //非生图模型的处理
    switch (model) {
        case 'grok-2':
            result.token = response?.token;
            return result;
        case 'grok-2-search':
        case 'grok-3-search':
            if (response?.webSearchResults && CONFIG.ISSHOW_SEARCH_RESULTS) {
                result.token = `\r\n<think>${await Utils.organizeSearchResults(response.webSearchResults)}</think>\r\n`;
            } else {
                result.token = response?.token;
            }
            return result;
        case 'grok-3':
            result.token = response?.token;
            return result;
        case 'grok-3-deepsearch':
            if (response?.messageTag === "final") {
                result.token = response?.token;
            }
            return result;
        case 'grok-3-reasoning':
            if (response?.isThinking && !CONFIG.SHOW_THINKING) return result;

            if (response?.isThinking && !CONFIG.IS_THINKING) {
                result.token = "<think>" + response?.token;
                CONFIG.IS_THINKING = true;
            } else if (!response.isThinking && CONFIG.IS_THINKING) {
                result.token = "</think>" + response?.token;
                CONFIG.IS_THINKING = false;
            } else {
                result.token = response?.token;
            }
            return result;
    }
    return result;
}

async function handleResponse(response, model, res, isStream) {
    try {
        const stream = response.body;
        let buffer = '';
        let fullResponse = '';
        const dataPromises = [];
        if (isStream) {
            res.setHeader('Content-Type', 'text/event-stream');
            res.setHeader('Cache-Control', 'no-cache');
            res.setHeader('Connection', 'keep-alive');
        }
        CONFIG.IS_THINKING = false;
        CONFIG.IS_IMG_GEN = false;
        CONFIG.IS_IMG_GEN2 = false;
        Logger.info("开始处理流式响应", 'Server');

        return new Promise((resolve, reject) => {
            stream.on('data', async (chunk) => {
                buffer += chunk.toString();
                const lines = buffer.split('\n');
                buffer = lines.pop() || '';

                for (const line of lines) {
                    if (!line.trim()) continue;
                    try {
                        const linejosn = JSON.parse(line.trim());
                        if (linejosn?.error) {
                            Logger.error(JSON.stringify(linejosn, null, 2), 'Server');
                            if (linejosn.error?.name === "RateLimitError") {
                                CONFIG.API.TEMP_COOKIE = null;
                            }
                            stream.destroy();
                            reject(new Error("RateLimitError"));
                            return;
                        }
                        let response = linejosn?.result?.response;
                        if (!response) continue;
                        if (response?.doImgGen || response?.imageAttachmentInfo) {
                            CONFIG.IS_IMG_GEN = true;
                        }
                        const processPromise = (async () => {
                            const result = await processModelResponse(response, model);

                            if (result.token) {
                                if (isStream) {
                                    res.write(`data: ${JSON.stringify(MessageProcessor.createChatResponse(result.token, model, true))}\n\n`);
                                } else {
                                    fullResponse += result.token;
                                }
                            }
                            if (result.imageUrl) {
                                CONFIG.IS_IMG_GEN2 = true;
                                const dataImage = await handleImageResponse(result.imageUrl);
                                if (isStream) {
                                    res.write(`data: ${JSON.stringify(MessageProcessor.createChatResponse(dataImage, model, true))}\n\n`);
                                } else {
                                    res.json(MessageProcessor.createChatResponse(dataImage, model));
                                }
                            }
                        })();
                        dataPromises.push(processPromise);
                    } catch (error) {
                        Logger.error(error, 'Server');
                        continue;
                    }
                }
            });

            stream.on('end', async () => {
                try {
                    await Promise.all(dataPromises);
                    if (isStream) {
                        res.write('data: [DONE]\n\n');
                        res.end();
                    } else {
                        if (!CONFIG.IS_IMG_GEN2) {
                            res.json(MessageProcessor.createChatResponse(fullResponse, model));
                        }
                    }
                    resolve();
                } catch (error) {
                    Logger.error(error, 'Server');
                    reject(error);
                }
            });

            stream.on('error', (error) => {
                Logger.error(error, 'Server');
                reject(error);
            });
        });
    } catch (error) {
        Logger.error(error, 'Server');
        throw new Error(error);
    }
}

async function handleImageResponse(imageUrl) {
    const MAX_RETRIES = 2;
    let retryCount = 0;
    let imageBase64Response;

    while (retryCount < MAX_RETRIES) {
        try {
            imageBase64Response = await fetch(`https://assets.grok.com/${imageUrl}`, {
                method: 'GET',
                headers: {
                    ...DEFAULT_HEADERS,
                    "cookie": CONFIG.API.SIGNATURE_COOKIE
                }
            });

            if (imageBase64Response.ok) break;
            retryCount++;
            if (retryCount === MAX_RETRIES) {
                throw new Error(`上游服务请求失败! status: ${imageBase64Response.status}`);
            }
            await new Promise(resolve => setTimeout(resolve, CONFIG.API.RETRY_TIME * retryCount));

        } catch (error) {
            Logger.error(error, 'Server');
            retryCount++;
            if (retryCount === MAX_RETRIES) {
                throw error;
            }
            await new Promise(resolve => setTimeout(resolve, CONFIG.API.RETRY_TIME * retryCount));
        }
    }


    const arrayBuffer = await imageBase64Response.arrayBuffer();
    const imageBuffer = Buffer.from(arrayBuffer);

    if (!CONFIG.API.PICGO_KEY && !CONFIG.API.TUMY_KEY) {
        const base64Image = imageBuffer.toString('base64');
        const imageContentType = imageBase64Response.headers.get('content-type');
        return `![image](data:${imageContentType};base64,${base64Image})`
    }

    Logger.info("开始上传图床", 'Server');
    const formData = new FormData();
    if (CONFIG.API.PICGO_KEY) {
        formData.append('source', imageBuffer, {
            filename: `image-${Date.now()}.jpg`,
            contentType: 'image/jpeg'
        });
        const formDataHeaders = formData.getHeaders();
        const responseURL = await fetch("https://www.picgo.net/api/1/upload", {
            method: "POST",
            headers: {
                ...formDataHeaders,
                "Content-Type": "multipart/form-data",
                "X-API-Key": CONFIG.API.PICGO_KEY
            },
            body: formData
        });
        if (!responseURL.ok) {
            return "生图失败，请查看PICGO图床密钥是否设置正确"
        } else {
            Logger.info("生图成功", 'Server');
            const result = await responseURL.json();
            return `![image](${result.image.url})`
        }
    } else if (CONFIG.API.TUMY_KEY) {
        const formData = new FormData();
        formData.append('file', imageBuffer, {
            filename: `image-${Date.now()}.jpg`,
            contentType: 'image/jpeg'
        });
        const formDataHeaders = formData.getHeaders();
        const responseURL = await fetch("https://tu.my/api/v1/upload", {
            method: "POST",
            headers: {
                ...formDataHeaders,
                "Accept": "application/json",
                'Authorization': `Bearer ${CONFIG.API.TUMY_KEY}`
            },
            body: formData
        });
        if (!responseURL.ok) {
            return "生图失败，请查看TUMY图床密钥是否设置正确"
        } else {
            try {
                const result = await responseURL.json();
                Logger.info("生图成功", 'Server');
                return `![image](${result.data.links.url})`
            } catch (error) {
                Logger.error(error, 'Server');
                return "生图失败，请查看TUMY图床密钥是否设置正确"
            }
        }
    }
}

const tokenManager = new AuthTokenManager();
const tempCookieManager = new GrokTempCookieManager();
await initialization();

// 中间件配置
const app = express();
app.use(Logger.requestLogger);
app.use(express.json({ limit: CONFIG.SERVER.BODY_LIMIT }));
app.use(express.urlencoded({ extended: true, limit: CONFIG.SERVER.BODY_LIMIT }));
app.use(cors({
    origin: '*',
    methods: ['GET', 'POST', 'OPTIONS'],
    allowedHeaders: ['Content-Type', 'Authorization']
}));


app.get('/get/tokens', (req, res) => {
    const authToken = req.headers.authorization?.replace('Bearer ', '');
    if (CONFIG.API.IS_CUSTOM_SSO) {
        return res.status(403).json({ error: '自定义的SSO令牌模式无法获取轮询sso令牌状态' });
    } else if (authToken !== CONFIG.API.API_KEY) {
        return res.status(401).json({ error: 'Unauthorized' });
    }
    res.json(tokenManager.getTokenStatusMap());
});
app.post('/add/token', async (req, res) => {
    const authToken = req.headers.authorization?.replace('Bearer ', '');
    if (CONFIG.API.IS_CUSTOM_SSO) {
        return res.status(403).json({ error: '自定义的SSO令牌模式无法添加sso令牌' });
    } else if (authToken !== CONFIG.API.API_KEY) {
        return res.status(401).json({ error: 'Unauthorized' });
    }
    try {
        const sso = req.body.sso;
        await tokenManager.addToken(`sso-rw=${sso};sso=${sso}`);
        res.status(200).json(tokenManager.getTokenStatusMap()[sso]);
    } catch (error) {
        Logger.error(error, 'Server');
        res.status(500).json({ error: '添加sso令牌失败' });
    }
});
app.post('/delete/token', async (req, res) => {
    const authToken = req.headers.authorization?.replace('Bearer ', '');
    if (CONFIG.API.IS_CUSTOM_SSO) {
        return res.status(403).json({ error: '自定义的SSO令牌模式无法删除sso令牌' });
    } else if (authToken !== CONFIG.API.API_KEY) {
        return res.status(401).json({ error: 'Unauthorized' });
    }
    try {
        const sso = req.body.sso;
        await tokenManager.deleteToken(`sso-rw=${sso};sso=${sso}`);
        res.status(200).json({ message: '删除sso令牌成功' });
    } catch (error) {
        Logger.error(error, 'Server');
        res.status(500).json({ error: '删除sso令牌失败' });
    }
});

app.get('/v1/models', (req, res) => {
    res.json({
        object: "list",
        data: Object.keys(tokenManager.tokenModelMap).map((model, index) => ({
            id: model,
            object: "model",
            created: Math.floor(Date.now() / 1000),
            owned_by: "grok",
        }))
    });
});


app.post('/v1/chat/completions', async (req, res) => {
    try {
        const authToken = req.headers.authorization?.replace('Bearer ', '');
        if (CONFIG.API.IS_CUSTOM_SSO) {
            if (authToken) {
                const result = `sso=${authToken};ssp_rw=${authToken}`;
                tokenManager.setToken(result);
            } else {
                return res.status(401).json({ error: '自定义的SSO令牌缺失' });
            }
        } else if (authToken !== CONFIG.API.API_KEY) {
            return res.status(401).json({ error: 'Unauthorized' });
        }
        const { model, stream } = req.body;
        let isTempCookie = model.includes("grok-2") && CONFIG.API.IS_TEMP_GROK2;
        let retryCount = 0;
        const grokClient = new GrokApiClient(model);
        const requestPayload = await grokClient.prepareChatRequest(req.body);
        //Logger.info(`请求体: ${JSON.stringify(requestPayload, null, 2)}`, 'Server');

        while (retryCount < CONFIG.RETRY.MAX_ATTEMPTS) {
            retryCount++;
            if (isTempCookie) {
                CONFIG.API.SIGNATURE_COOKIE = CONFIG.API.TEMP_COOKIE;
                Logger.info(`已切换为临时令牌`, 'Server');
            } else {
                CONFIG.API.SIGNATURE_COOKIE = await Utils.createAuthHeaders(model);
            }
            if (!CONFIG.API.SIGNATURE_COOKIE) {
                throw new Error('该模型无可用令牌');
            }
            Logger.info(`当前令牌: ${JSON.stringify(CONFIG.API.SIGNATURE_COOKIE, null, 2)}`, 'Server');
            Logger.info(`当前可用模型的全部可用数量: ${JSON.stringify(tokenManager.getRemainingTokenRequestCapacity(), null, 2)}`, 'Server');
            const response = await fetch(`${CONFIG.API.BASE_URL}/rest/app-chat/conversations/new`, {
                method: 'POST',
                headers: {
                    "accept": "text/event-stream",
                    "baggage": "sentry-public_key=b311e0f2690c81f25e2c4cf6d4f7ce1c",
                    "content-type": "text/plain;charset=UTF-8",
                    "Connection": "keep-alive",
                    "cookie": CONFIG.API.SIGNATURE_COOKIE
                },
                body: JSON.stringify(requestPayload)
            });

            if (response.ok) {
                Logger.info(`请求成功`, 'Server');
                Logger.info(`当前${model}剩余可用令牌数: ${tokenManager.getTokenCountForModel(model)}`, 'Server');
                try {
                    await handleResponse(response, model, res, stream);
                    Logger.info(`请求结束`, 'Server');
                    return;
                } catch (error) {
                    Logger.error(error, 'Server');
                    if (isTempCookie) {
                        tempCookieManager.cookies.splice(tempCookieManager.currentIndex, 1);
                        if (tempCookieManager.cookies.length != 0) {
                            tempCookieManager.currentIndex = tempCookieManager.currentIndex % tempCookieManager.cookies.length;
                            CONFIG.API.TEMP_COOKIE = tempCookieManager.cookies[tempCookieManager.currentIndex];
                            tempCookieManager.ensureCookies()
                        } else {
                            try {
                                await tempCookieManager.ensureCookies();
                                tempCookieManager.currentIndex = tempCookieManager.currentIndex % tempCookieManager.cookies.length;
                                CONFIG.API.TEMP_COOKIE = tempCookieManager.cookies[tempCookieManager.currentIndex];
                            } catch (error) {
                                throw error;
                            }
                        }
                    } else {
                        if (CONFIG.API.IS_CUSTOM_SSO) throw new Error(`自定义SSO令牌当前模型${model}的请求次数已失效`);
                        tokenManager.removeTokenFromModel(model, CONFIG.API.SIGNATURE_COOKIE.cookie);
                        if (tokenManager.getTokenCountForModel(model) === 0) {
                            throw new Error(`${model} 次数已达上限，请切换其他模型或者重新对话`);
                        }
                    }
                }
            } else {
                if (response.status === 429) {
                    if (isTempCookie) {
                        // 移除当前失效的 cookie
                        tempCookieManager.cookies.splice(tempCookieManager.currentIndex, 1);
                        if (tempCookieManager.cookies.length != 0) {
                            tempCookieManager.currentIndex = tempCookieManager.currentIndex % tempCookieManager.cookies.length;
                            CONFIG.API.TEMP_COOKIE = tempCookieManager.cookies[tempCookieManager.currentIndex];
                            tempCookieManager.ensureCookies()
                        } else {
                            try {
                                await tempCookieManager.ensureCookies();
                                tempCookieManager.currentIndex = tempCookieManager.currentIndex % tempCookieManager.cookies.length;
                                CONFIG.API.TEMP_COOKIE = tempCookieManager.cookies[tempCookieManager.currentIndex];
                            } catch (error) {
                                throw error;
                            }
                        }
                    } else {
                        if (CONFIG.API.IS_CUSTOM_SSO) throw new Error(`自定义SSO令牌当前模型${model}的请求次数已失效`);
                        tokenManager.removeTokenFromModel(model, CONFIG.API.SIGNATURE_COOKIE.cookie);
                        if (tokenManager.getTokenCountForModel(model) === 0) {
                            throw new Error(`${model} 次数已达上限，请切换其他模型或者重新对话`);
                        }
                    }
                } else {
                    // 非429错误直接抛出
                    if (isTempCookie) {
                        // 移除当前失效的 cookie
                        tempCookieManager.cookies.splice(tempCookieManager.currentIndex, 1);
                        if (tempCookieManager.cookies.length != 0) {
                            tempCookieManager.currentIndex = tempCookieManager.currentIndex % tempCookieManager.cookies.length;
                            CONFIG.API.TEMP_COOKIE = tempCookieManager.cookies[tempCookieManager.currentIndex];
                            tempCookieManager.ensureCookies()
                        } else {
                            try {
                                await tempCookieManager.ensureCookies();
                                tempCookieManager.currentIndex = tempCookieManager.currentIndex % tempCookieManager.cookies.length;
                                CONFIG.API.TEMP_COOKIE = tempCookieManager.cookies[tempCookieManager.currentIndex];
                            } catch (error) {
                                throw error;
                            }
                        }
                    } else {
                        if (CONFIG.API.IS_CUSTOM_SSO) throw new Error(`自定义SSO令牌当前模型${model}的请求次数已失效`);
                        Logger.error(`令牌异常错误状态!status: ${response.status}`, 'Server');
                        tokenManager.removeTokenFromModel(model, CONFIG.API.SIGNATURE_COOKIE.cookie);
                        Logger.info(`当前${model}剩余可用令牌数: ${tokenManager.getTokenCountForModel(model)}`, 'Server');
                    }
                }
            }
        }
        throw new Error('当前模型所有令牌都已耗尽');
    } catch (error) {
        Logger.error(error, 'ChatAPI');
        res.status(500).json({
            error: {
                message: error.message || error,
                type: 'server_error'
            }
        });
    }
});


app.use((req, res) => {
    res.status(200).send('api运行正常');
});


app.listen(CONFIG.SERVER.PORT, () => {
    Logger.info(`服务器已启动，监听端口: ${CONFIG.SERVER.PORT}`, 'Server');
});
