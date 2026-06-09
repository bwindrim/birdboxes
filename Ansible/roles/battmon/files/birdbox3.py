"""
Launcher for birdbox3 implementation.
Delegates hardware-specific behavior to `birdbox3_impl` and core logic to `body`.
"""
import body
import birdbox3_impl as impl

if __name__ == '__main__':
    body.main(impl)
