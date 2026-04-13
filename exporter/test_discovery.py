# exporter/test_discovery.py

import json
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

from collectors.llm_discovery import discover_active_llms

def main():
    print("--- Starting LLM Process Discovery Test ---")

    try:
        active_providers = discover_active_llms()
        print("\n--- Discovery Results ---")
        if not active_providers:
            print("No LLM runtimes detected.")
        else:
            for provider in active_providers:
                print(f"\nEngine: {provider.ENGINE_NAME}")
                print(f"  PID: {provider.pid}")
                print(f"  Port: {provider.port}")

                # Test API fetching capabilities
                model = provider.get_active_model()
                stats = provider.get_stats()

                print(f"  Active Model: {model if model else 'N/A'}")
                print(f"  Stats: {json.dumps(stats, indent=4) if stats else 'N/A'}")

        print("\n--- Test Complete ---")

    except Exception as e:
        import traceback
        print(f"Error during discovery test: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    main()