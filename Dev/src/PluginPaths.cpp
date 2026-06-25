#include "PluginPaths.h"

#include <Windows.h>

#include <stdexcept>

extern "C" IMAGE_DOS_HEADER __ImageBase;

namespace
{
	std::filesystem::path ResolvePluginDirectory()
	{
		std::wstring modulePath(512, L'\0');

		for (;;)
		{
			const DWORD length = GetModuleFileNameW(
				reinterpret_cast<HMODULE>(&__ImageBase),
				modulePath.data(),
				static_cast<DWORD>(modulePath.size()));

			if (length == 0)
			{
				throw std::runtime_error("Failed to resolve the plugin DLL path.");
			}

			if (length < modulePath.size() - 1)
			{
				modulePath.resize(length);
				return std::filesystem::path(modulePath).parent_path();
			}

			modulePath.resize(modulePath.size() * 2);
		}
	}

	std::filesystem::path ResolveDataDirectory()
	{
		const std::filesystem::path pluginDirectory = ResolvePluginDirectory();
		const std::filesystem::path dataDirectory = pluginDirectory / L"SC4-3DMouseCam";
		std::error_code error;
		std::filesystem::create_directories(dataDirectory, error);
		if (error && !std::filesystem::is_directory(dataDirectory))
		{
			throw std::runtime_error("Failed to create the SC4-3DMouseCam data directory.");
		}

		// Migrate the files created by pre-0.7 development builds. This runs
		// before the logger and settings file are opened.
		constexpr const wchar_t* legacyFiles[] = {
			L"SC4-3DMouseCam.json",
			L"SC4-3DMouseCam.log",
			L"SC4-3DMouseCam.last",
			L"test.json",
		};
		for (const wchar_t* fileName : legacyFiles)
		{
			const std::filesystem::path source = pluginDirectory / fileName;
			const std::filesystem::path destination = dataDirectory / fileName;
			if (std::filesystem::exists(source) && !std::filesystem::exists(destination))
			{
				error.clear();
				std::filesystem::rename(source, destination, error);
				if (error)
				{
					error.clear();
					std::filesystem::copy_file(
						source, destination, std::filesystem::copy_options::none, error);
					if (!error)
					{
						std::filesystem::remove(source, error);
					}
				}
			}
		}
		return dataDirectory;
	}
}

const std::filesystem::path& PluginPaths::GetPluginDirectory()
{
	static const std::filesystem::path directory = ResolvePluginDirectory();
	return directory;
}

const std::filesystem::path& PluginPaths::GetDataDirectory()
{
	static const std::filesystem::path directory = ResolveDataDirectory();
	return directory;
}

std::filesystem::path PluginPaths::GetSettingsPath()
{
	return GetDataDirectory() / L"SC4-3DMouseCam.json";
}

std::filesystem::path PluginPaths::GetLogPath()
{
	return GetDataDirectory() / L"SC4-3DMouseCam.log";
}

std::filesystem::path PluginPaths::GetTestSettingsPath()
{
	return GetDataDirectory() / L"test.json";
}
