import argparse
import sys
from agent.agent import Agent

def main():
    parser = argparse.ArgumentParser(description="Local AI Coding Agent")
    parser.add_argument("goal", type=str, help="The goal for the agent to achieve")
    
    args = parser.parse_args()
    
    print("Initializing Agent...")
    try:
        agent = Agent(goal=args.goal)
        agent.run()
    except KeyboardInterrupt:
        print("\nAgent interrupted by user.")
        sys.exit(0)
    except Exception as e:
        print(f"\nAn error occurred: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
