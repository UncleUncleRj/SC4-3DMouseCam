#include <Windows.h>
#include "cRZCOMDllDirector.h"
#include "Logger.h"
#include "cIGZMessageServer2.h"
#include "cIGZMessageTarget2.h"
#include "cIGZMessage2Standard.h"
#include "GZServPtrs.h"

static constexpr uint32_t kSC4MessagePostCityInit = 0x26D31EC1;
static constexpr uint32_t kSC4MessagePreCityShutdown = 0x26D31EC2;

// Global State
bool g_IsCityLoaded = false;
HHOOK g_MouseHook = NULL;
HHOOK g_KeyboardHook = NULL;
bool g_KeyState[256] = { false };

std::string GetKeyName(DWORD vkCode) {
    switch (vkCode) {
        case VK_MENU: case VK_LMENU: case VK_RMENU: return "ALT";
        case VK_SHIFT: case VK_LSHIFT: case VK_RSHIFT: return "SHIFT";
        case VK_CONTROL: case VK_LCONTROL: case VK_RCONTROL: return "CTRL";
        case 'W': return "W";
        case 'A': return "A";
        case 'S': return "S";
        case 'D': return "D";
        case VK_UP: return "Up Arrow";
        case VK_DOWN: return "Down Arrow";
        case VK_LEFT: return "Left Arrow";
        case VK_RIGHT: return "Right Arrow";
        default: return "Other Key (" + std::to_string(vkCode) + ")";
    }
}

LRESULT CALLBACK MouseHookProc(int nCode, WPARAM wParam, LPARAM lParam) {
    if (nCode >= 0 && g_IsCityLoaded) {
        // Only log if SC4 is the active window
        DWORD fgPid = 0;
        GetWindowThreadProcessId(GetForegroundWindow(), &fgPid);
        if (fgPid == GetCurrentProcessId()) {
            MSLLHOOKSTRUCT* pMouse = reinterpret_cast<MSLLHOOKSTRUCT*>(lParam);
            Logger& log = Logger::GetInstance();
            
            std::string coords = " -- (X: " + std::to_string(pMouse->pt.x) + ", Y: " + std::to_string(pMouse->pt.y) + ")";

            switch (wParam) {
                case WM_LBUTTONDOWN: log.WriteLine(LogLevel::Info, "Mouse 1 (Left) Pressed" + coords); break;
                case WM_LBUTTONUP:   log.WriteLine(LogLevel::Info, "Mouse 1 (Left) Released" + coords); break;
                case WM_RBUTTONDOWN: log.WriteLine(LogLevel::Info, "Mouse 2 (Right) Pressed" + coords); break;
                case WM_RBUTTONUP:   log.WriteLine(LogLevel::Info, "Mouse 2 (Right) Released" + coords); break;
                case WM_MBUTTONDOWN: log.WriteLine(LogLevel::Info, "Mouse 3 (Middle) Pressed" + coords); break;
                case WM_MBUTTONUP:   log.WriteLine(LogLevel::Info, "Mouse 3 (Middle) Released" + coords); break;
                case WM_MOUSEWHEEL: {
                    short zDelta = HIWORD(pMouse->mouseData);
                    if (zDelta > 0) log.WriteLine(LogLevel::Info, "Mouse Wheel Up" + coords);
                    else log.WriteLine(LogLevel::Info, "Mouse Wheel Down" + coords);
                    break;
                }
            }
        }
    }
    return CallNextHookEx(g_MouseHook, nCode, wParam, lParam);
}

LRESULT CALLBACK KeyboardHookProc(int nCode, WPARAM wParam, LPARAM lParam) {
    if (nCode >= 0 && g_IsCityLoaded) {
        DWORD fgPid = 0;
        GetWindowThreadProcessId(GetForegroundWindow(), &fgPid);
        if (fgPid == GetCurrentProcessId()) {
            KBDLLHOOKSTRUCT* pKey = reinterpret_cast<KBDLLHOOKSTRUCT*>(lParam);
            Logger& log = Logger::GetInstance();
            
            DWORD vkCode = pKey->vkCode;
            
            // Normalize left/right modifiers to their standard generic code so the array checks properly
            if (vkCode == VK_LSHIFT || vkCode == VK_RSHIFT) vkCode = VK_SHIFT;
            if (vkCode == VK_LCONTROL || vkCode == VK_RCONTROL) vkCode = VK_CONTROL;
            if (vkCode == VK_LMENU || vkCode == VK_RMENU) vkCode = VK_MENU;

            if (vkCode == VK_MENU || vkCode == VK_SHIFT || vkCode == VK_CONTROL ||
                vkCode == 'W' || vkCode == 'A' || vkCode == 'S' || vkCode == 'D' ||
                vkCode == VK_UP || vkCode == VK_DOWN || vkCode == VK_LEFT || vkCode == VK_RIGHT) {
                
                std::string keyName = GetKeyName(vkCode);
                
                if (wParam == WM_KEYDOWN || wParam == WM_SYSKEYDOWN) {
                    if (!g_KeyState[vkCode]) {
                        g_KeyState[vkCode] = true;
                        log.WriteLine(LogLevel::Info, "Keyboard '" + keyName + "' Pressed");
                    } else {
                        // It's auto-repeating, log as Held (optional, might spam a bit but good for debugging holds)
                        log.WriteLine(LogLevel::Info, "Keyboard '" + keyName + "' Held");
                    }
                } else if (wParam == WM_KEYUP || wParam == WM_SYSKEYUP) {
                    g_KeyState[vkCode] = false;
                    log.WriteLine(LogLevel::Info, "Keyboard '" + keyName + "' Released");
                }
            }
        }
    }
    return CallNextHookEx(g_KeyboardHook, nCode, wParam, lParam);
}

class cSC4MouseCamDirector : public cRZCOMDllDirector, public cIGZMessageTarget2
{
public:
	cSC4MouseCamDirector()
	{
		AddRef();
	}

    // Resolve COM multiple inheritance ambiguity
    uint32_t AddRef() override { return cRZCOMDllDirector::AddRef(); }
    uint32_t Release() override { return cRZCOMDllDirector::Release(); }

    bool QueryInterface(uint32_t riid, void** ppvObj) override
    {
        // GZIID_cIGZMessageTarget2 is 0x090fa124 based on the header file definition
        if (riid == 0x090fa124) {
            *ppvObj = static_cast<cIGZMessageTarget2*>(this);
            AddRef();
            return true;
        }
        return cRZCOMDllDirector::QueryInterface(riid, ppvObj);
    }

	uint32_t GetDirectorID() const override
	{
		return 0x8C4B3A11;
	}

	bool OnStart(cIGZCOM* pCOM) override
	{
		Logger::GetInstance().Initialize("C:\\Users\\minus\\Documents\\SimCity 4\\Plugins\\SC4-3DMouseCam.log");
		Logger::GetInstance().WriteLine(LogLevel::Info, "Plugin Loaded. Waiting for city to load...");

        // Register to receive messages from the game
        cIGZMessageServer2Ptr pMsgServ;
        if (pMsgServ) {
            pMsgServ->AddNotification(this, kSC4MessagePostCityInit);
            pMsgServ->AddNotification(this, kSC4MessagePreCityShutdown);
        }

		return true;
	}
    
    bool DoMessage(cIGZMessage2* pMsg) override
    {
        uint32_t msgType = pMsg->GetType();

        if (msgType == kSC4MessagePostCityInit) {
            Logger::GetInstance().WriteLine(LogLevel::Info, "City Loaded! Activating Hooks...");
            g_IsCityLoaded = true;
            memset(g_KeyState, 0, sizeof(g_KeyState)); // Reset key states just in case
            
            // Install Windows API Hooks
            if (!g_MouseHook) {
                g_MouseHook = SetWindowsHookEx(WH_MOUSE_LL, MouseHookProc, GetModuleHandle(NULL), 0);
            }
            if (!g_KeyboardHook) {
                g_KeyboardHook = SetWindowsHookEx(WH_KEYBOARD_LL, KeyboardHookProc, GetModuleHandle(NULL), 0);
            }
        }
        else if (msgType == kSC4MessagePreCityShutdown) {
            Logger::GetInstance().WriteLine(LogLevel::Info, "City Shutting Down. Deactivating Hooks...");
            g_IsCityLoaded = false;
            
            // Remove Windows API Hooks
            if (g_MouseHook) {
                UnhookWindowsHookEx(g_MouseHook);
                g_MouseHook = NULL;
            }
            if (g_KeyboardHook) {
                UnhookWindowsHookEx(g_KeyboardHook);
                g_KeyboardHook = NULL;
            }
        }

        return true;
    }
};

cRZCOMDllDirector* RZGetCOMDllDirector() {
	static cSC4MouseCamDirector sDirector;
	return &sDirector;
}
