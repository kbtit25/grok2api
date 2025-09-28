import got from "got";
import { CookieJar } from "tough-cookie";
import { HttpsProxyAgent } from "https-proxy-agent";
// npm i puppeteer-real-browser tough-cookie got https-proxy-agent

const PROXY_URL = "http://1.1.1.1:1999";
const PROXY_USER = "";
const PROXY_PASS = "";
const TEMPMAIL_URL = "https://tempmail.so/us/api/inbox?lang=us/";

class Headers {
    constructor() {
        this.ua =
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0 Safari/537.36";
        this.ct = "application/json";
        this.ac = "application/json";
    }

    asDict() {
        return {
            "user-agent": this.ua,
            "content-type": this.ct,
            accept: this.ac,
        };
    }
}

export class TempMailTimeout extends Error {
    constructor(message) {
        super(message);
        this.name = "TempMailTimeout";
    }
}

export class EmailClient {
    constructor(proxyUrl = PROXY_URL, proxyUser = PROXY_USER, proxyPass = PROXY_PASS) {
        this.headers = new Headers().asDict();
        this.cookieJar = new CookieJar();

        // Create proxy agent with authentication
        const proxyWithAuth = proxyUser && proxyPass 
            ? proxyUrl.replace('://', `://${proxyUser}:${proxyPass}@`)
            : proxyUrl;
        
        const proxyAgent = new HttpsProxyAgent(proxyWithAuth);

        // Create got instance with proper configuration
        this.client = got.extend({
            headers: this.headers,
            cookieJar: this.cookieJar,
            timeout: {
                request: 30000
            },
            // agent: {
            //     http: proxyAgent,
            //     https: proxyAgent
            // },
            retry: {
                limit: 0 // Disable automatic retries to handle them manually
            }
        });
    }

    async getIp() {
        try {
            const response = await this.client.get("https://api64.ipify.org?format=json").json();
            console.log("Your IP:", response.ip);
            return response.ip;
        } catch (err) {
            console.error("Failed to fetch IP:", err.message);
            return null;
        }
    }

    async fetchJson(url) {
        const response = await this.client.get(url).json();
        return response;
    }

    async getEmail(retries = 5, delay = 2) {
        for (let i = 0; i < retries; i++) {
            try {
                const data = await this.fetchJson(TEMPMAIL_URL);
                const email = data?.data?.name;
                if (email) return email;
                await this.sleep(delay * 1000);
            } catch (error) {
                if (i === retries - 1) throw error;
                await this.sleep(delay * 1000);
            }
        }
        return null;
    }

    async getCode(timeout = 30, delay = 2) {
        const endTime = Date.now() + timeout * 1000;

        while (Date.now() < endTime) {
            try {
                const data = await this.fetchJson(TEMPMAIL_URL);
                const inbox = data?.data?.inbox || [];

                for (const msg of inbox) {
                    const subject = msg.subject;
                    if (subject) {
                        const parts = subject.split(" ");
                        if (parts.length > 0) {
                            const code = parts[0].replace(/-/g, "");
                            return code;
                        }
                    }
                }
            } catch (error) {
                // retry
            }
            await this.sleep(delay * 1000);
        }

        throw new TempMailTimeout("Timeout: No code received.");
    }

    sleep(ms) {
        return new Promise((resolve) => setTimeout(resolve, ms));
    }

    async close() {
        // Got doesn't require explicit cleanup
    }
}

// Example usage
async function main() {
    const client = new EmailClient();

    await client.getIp(); // should show proxy IP
    const email = await client.getEmail();
    console.log("Email:", email);

    const code = await client.getCode();
    console.log("Code:", code);
}

// main().catch(console.error); 