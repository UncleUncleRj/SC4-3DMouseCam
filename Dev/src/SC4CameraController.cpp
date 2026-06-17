#include "SC4CameraController.h"

#include "GZServPtrs.h"
#include "Logger.h"
#include "cIGZWin.h"
#include "cISC43DRender.h"
#include "cISC4App.h"
#include "cISC4View3DWin.h"

#include <Windows.h>

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <string>

namespace
{
	constexpr uint32_t kGZWin_WinSC4App = 0x6104489a;
	constexpr uint32_t kGZWin_SC4View3DWin = 0x9a47b417;
	constexpr uint32_t kCameraUpdateMode = 2;
	constexpr size_t kZoomCount = 5;

	constexpr uintptr_t kPitchAddress1 = 0x00ABCFD8;
	constexpr uintptr_t kPitchAddress2 = 0x00ABACCC;
	constexpr uintptr_t kYawAddress0 = 0x007CCB0A;
	constexpr uintptr_t kYawAddress1 = 0x00ABCFC4;
	constexpr uintptr_t kYawAddress2 = 0x00ABACB8;

	using UpdateCameraPositionFn = bool(__thiscall*)(SC4CameraControlLayout*, uint32_t);

	UpdateCameraPositionFn GetUpdateCameraPosition()
	{
		return reinterpret_cast<UpdateCameraPositionFn>(0x007CCF80);
	}

	template <typename Function>
	bool WithRenderer(Function&& function)
	{
		cISC4AppPtr pSC4App;
		if (!pSC4App) {
			return false;
		}

		cIGZWin* mainWindow = pSC4App->GetMainWindow();
		if (!mainWindow) {
			return false;
		}

		cIGZWin* pParentWin = mainWindow->GetChildWindowFromID(kGZWin_WinSC4App);
		if (!pParentWin) {
			return false;
		}

		cISC4View3DWin* pView3D = nullptr;
		if (!pParentWin->GetChildAs(kGZWin_SC4View3DWin, kGZIID_cISC4View3DWin, reinterpret_cast<void**>(&pView3D))) {
			return false;
		}

		bool result = false;
		cISC43DRender* renderer = pView3D->GetRenderer();
		if (renderer) {
			result = function(renderer);
		}

		pView3D->Release();
		return result;
	}
}

SC4CameraController::SC4CameraController()
	: currentPitch(kDefaultPitch),
	  currentYaw(kDefaultYaw)
{
}

float SC4CameraController::GetPitch() const
{
	return currentPitch;
}

float SC4CameraController::GetYaw() const
{
	return currentYaw;
}

void SC4CameraController::Reset()
{
	currentPitch = kDefaultPitch;
	currentYaw = kDefaultYaw;
}

bool SC4CameraController::ApplyDelta(float pitchDelta, float yawDelta, bool updateYaw)
{
	currentPitch = SanitizePitch(currentPitch + pitchDelta);
	currentYaw = SanitizeYaw(currentYaw + yawDelta);

	ApplyPitchOverride(currentPitch);

	if (updateYaw) {
		ApplyYawOverride(currentYaw);
	}

	SC4CameraControlLayout* cameraControl = GetActiveCameraControl();
	if (!cameraControl) {
		Logger::GetInstance().WriteLine(LogLevel::Error, "Failed to get SC4 camera control from renderer.");
		return false;
	}

	cameraControl->pitch = currentPitch;

	if (updateYaw) {
		cameraControl->yaw = currentYaw;
	}

	return Refresh(*cameraControl);
}

bool SC4CameraController::ForceFullRedraw()
{
	return WithRenderer([](cISC43DRender* renderer) {
		return renderer->ForceFullRedraw();
	});
}

SC4CameraControlLayout* SC4CameraController::GetActiveCameraControl()
{
	SC4CameraControlLayout* cameraControl = nullptr;

	WithRenderer([&](cISC43DRender* renderer) {
		cameraControl = reinterpret_cast<SC4CameraControlLayout*>(renderer->GetCameraControl());
		return cameraControl != nullptr;
	});

	return cameraControl;
}

bool SC4CameraController::Refresh(SC4CameraControlLayout& cameraControl)
{
	auto updateCameraPosition = GetUpdateCameraPosition();
	if (!updateCameraPosition) {
		return false;
	}

	cameraControl.pitch = SanitizePitch(cameraControl.pitch);
	cameraControl.yaw = SanitizeYaw(cameraControl.yaw);

	return updateCameraPosition(&cameraControl, kCameraUpdateMode);
}

float SC4CameraController::SanitizePitch(float pitch)
{
	return std::clamp(pitch, kMinPitch, kMaxPitch);
}

float SC4CameraController::SanitizeYaw(float yaw)
{
	float normalizedYaw = std::fmod(yaw, 2.0f * kPi);

	if (normalizedYaw <= -kPi) {
		normalizedYaw += 2.0f * kPi;
	}
	else if (normalizedYaw > kPi) {
		normalizedYaw -= 2.0f * kPi;
	}

	return normalizedYaw;
}

void SC4CameraController::ApplyPitchOverride(float pitch)
{
	pitch = SanitizePitch(pitch);

	for (size_t i = 0; i < kZoomCount; i++) {
		OverwriteMemoryFloat(kPitchAddress1 + (i * sizeof(float)), pitch);
		OverwriteMemoryFloat(kPitchAddress2 + (i * sizeof(float)), pitch);
	}
}

void SC4CameraController::ApplyYawOverride(float yaw)
{
	yaw = SanitizeYaw(yaw);

	OverwriteMemoryFloat(kYawAddress0, yaw);

	for (size_t i = 0; i < kZoomCount; i++) {
		OverwriteMemoryFloat(kYawAddress1 + (i * sizeof(float)), yaw);
		OverwriteMemoryFloat(kYawAddress2 + (i * sizeof(float)), yaw);
	}
}

void SC4CameraController::OverwriteMemoryFloat(uintptr_t address, float value)
{
	DWORD oldProtect = 0;

	if (VirtualProtect(reinterpret_cast<void*>(address), sizeof(value), PAGE_EXECUTE_READWRITE, &oldProtect)) {
		*reinterpret_cast<float*>(address) = value;

		DWORD ignored = 0;
		VirtualProtect(reinterpret_cast<void*>(address), sizeof(value), oldProtect, &ignored);
	}
	else {
		char hexAddr[32];
		sprintf_s(hexAddr, sizeof(hexAddr), "0x%X", address);
		Logger::GetInstance().WriteLine(LogLevel::Error, std::string("VirtualProtect failed at ") + hexAddr);
	}
}
